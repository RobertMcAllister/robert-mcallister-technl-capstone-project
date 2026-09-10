"""Local GPU audio processing service.

Exposes FastAPI endpoints for the full audio pipeline:
  /clean              — Demucs music removal + normalization
  /transcribe         — Whisper transcription with word timestamps
  /diarize            — pyannote speaker diarization
  /segment            — Boundary detection + audio cutting into training clips
  /classify-emotions  — Dual-signal emotion classification (text + audio)

Start with: bash services/transcription/run.sh
"""

import hashlib
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

import boto3
import numpy as np
import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from faster_whisper import WhisperModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Capstone GPU Transcription + Cleaning Service")

# Load Whisper at startup
MODEL_SIZE = os.environ.get("WHISPER_MODEL", "medium")
DEVICE = os.environ.get("WHISPER_DEVICE", "cuda")
COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "float16")

logger.info(f"Loading Whisper {MODEL_SIZE} on {DEVICE} ({COMPUTE_TYPE})...")
whisper_model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
logger.info("Whisper loaded.")

# Lazy-loaded models (loaded on first call to each endpoint)
demucs_model = None
diarize_pipeline = None
text_emotion_pipeline = None
audio_emotion_model = None

s3 = boto3.client("s3", region_name="us-east-1")

PROCESSED_BUCKET = "robert-mcallister-processed"


def get_demucs_model():
    """Load Demucs model on first use."""
    global demucs_model
    if demucs_model is None:
        from demucs.pretrained import get_model
        logger.info("Loading Demucs htdemucs model...")
        demucs_model = get_model("htdemucs")
        demucs_model.to(torch.device("cuda"))
        logger.info("Demucs loaded.")
    return demucs_model


def get_diarize_pipeline():
    """Load pyannote speaker diarization on first use."""
    global diarize_pipeline
    if diarize_pipeline is None:
        from pyannote.audio import Pipeline
        logger.info("Loading pyannote speaker-diarization-community-1...")
        diarize_pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-community-1",
            token=os.environ.get("HF_TOKEN"),
        )
        diarize_pipeline.to(torch.device("cuda"))
        logger.info("Pyannote loaded.")
    return diarize_pipeline


def get_text_emotion_pipeline():
    """Load ModernBERT GoEmotions classifier on first use."""
    global text_emotion_pipeline
    if text_emotion_pipeline is None:
        from transformers import pipeline as hf_pipeline
        logger.info("Loading ModernBERT GoEmotions classifier...")
        text_emotion_pipeline = hf_pipeline(
            "text-classification",
            model="cirimus/modernbert-large-go-emotions",
            top_k=None,
            device=0,
        )
        logger.info("ModernBERT loaded.")
    return text_emotion_pipeline


def get_audio_emotion_model():
    """Load emotion2vec audio classifier on first use."""
    global audio_emotion_model
    if audio_emotion_model is None:
        from funasr import AutoModel
        logger.info("Loading emotion2vec_plus_large...")
        audio_emotion_model = AutoModel(model="iic/emotion2vec_plus_large")
        logger.info("emotion2vec loaded.")
    return audio_emotion_model


# Emotion mapping: GoEmotions 28 labels → 8 TTS tags
GOEMOTION_TO_TAG = {
    "joy": "happy", "amusement": "happy", "excitement": "excited",
    "love": "happy", "desire": "happy", "optimism": "happy",
    "caring": "neutral", "pride": "happy", "admiration": "happy",
    "gratitude": "happy", "relief": "happy", "approval": "neutral",
    "sadness": "sad", "grief": "sad", "remorse": "sad",
    "disappointment": "sad", "disapproval": "angry",
    "anger": "angry", "annoyance": "angry", "disgust": "angry",
    "fear": "fearful", "nervousness": "fearful",
    "surprise": "surprised", "realization": "surprised",
    "curiosity": "surprised", "confusion": "surprised",
    "embarrassment": "neutral", "neutral": "neutral",
}

EMOTION2VEC_LABELS = ["angry", "disgusted", "fearful", "happy", "neutral", "other", "sad", "surprised", "unknown"]

EMOTION2VEC_TO_TAG = {
    # English labels
    "angry": "angry", "disgusted": "angry", "fearful": "fearful",
    "happy": "happy", "neutral": "neutral", "other": "neutral",
    "sad": "sad", "surprised": "surprised", "unknown": "neutral",
    # Bilingual labels (funasr returns these)
    "生气/angry": "angry", "厌恶/disgusted": "angry", "恐惧/fearful": "fearful",
    "开心/happy": "happy", "中立/neutral": "neutral", "其他/other": "neutral",
    "难过/sad": "sad", "吃惊/surprised": "surprised", "<unk>": "neutral",
}


class S3Request(BaseModel):
    bucket: str
    key: str


class CleanResponse(BaseModel):
    cleaned_bucket: str
    cleaned_key: str
    original_key: str
    duration_seconds: float


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_SIZE, "device": DEVICE, "demucs": demucs_model is not None}


@app.post("/clean")
def clean(req: S3Request):
    """Download audio from S3, run Demucs vocal separation + normalization, upload cleaned audio back."""
    logger.info(f"Clean request: s3://{req.bucket}/{req.key}")

    suffix = Path(req.key).suffix or ".webm"
    stem = Path(req.key).stem

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_in:
        input_path = tmp_in.name
    output_path = input_path + "_cleaned.wav"

    try:
        # Download from S3
        s3.download_file(req.bucket, req.key, input_path)
        logger.info(f"Downloaded {input_path}")

        # Load audio with pydub
        from pydub import AudioSegment
        audio = AudioSegment.from_file(input_path)
        duration_seconds = len(audio) / 1000.0
        logger.info(f"Audio loaded: {duration_seconds:.1f}s, {audio.channels}ch, {audio.frame_rate}Hz")

        # Convert to mono float32 tensor for Demucs
        audio_mono = audio.set_channels(1)
        samples = np.array(audio_mono.get_array_of_samples(), dtype=np.float32)
        samples = samples / 32768.0  # int16 to float32 [-1, 1]

        # Demucs expects (batch, channels, samples) at 44100Hz
        from scipy import signal as scipy_signal
        if audio.frame_rate != 44100:
            num_samples_44k = int(len(samples) * 44100 / audio.frame_rate)
            samples = scipy_signal.resample(samples, num_samples_44k)

        tensor = torch.tensor(samples, dtype=torch.float32).unsqueeze(0).unsqueeze(0)  # (1, 1, samples)
        # Demucs expects stereo - duplicate mono to stereo
        tensor = tensor.expand(-1, 2, -1).to("cuda")

        # Run Demucs
        model = get_demucs_model()
        from demucs.apply import apply_model
        with torch.no_grad():
            sources = apply_model(model, tensor, device="cuda")
        # sources shape: (1, 4, 2, samples) - stems: drums, bass, other, vocals
        vocals = sources[0, 3]  # (2, samples) - vocals stem
        vocals_mono = vocals.mean(dim=0).cpu().numpy()  # average stereo to mono

        # Resample back to original rate if needed
        if audio.frame_rate != 44100:
            num_samples_orig = int(len(vocals_mono) * audio.frame_rate / 44100)
            vocals_mono = scipy_signal.resample(vocals_mono, num_samples_orig)

        # Normalize volume (simple peak normalization to -3dB)
        peak = np.abs(vocals_mono).max()
        if peak > 0:
            target_peak = 10 ** (-3.0 / 20.0)  # -3 dB
            vocals_mono = vocals_mono * (target_peak / peak)

        # Clip and convert to int16
        vocals_mono = np.clip(vocals_mono, -1.0, 1.0)
        vocals_int16 = (vocals_mono * 32767).astype(np.int16)

        # Write WAV
        from scipy.io import wavfile
        wavfile.write(output_path, audio.frame_rate, vocals_int16)
        logger.info(f"Cleaned audio written to {output_path}")

        # Upload to S3 cleaned/ prefix
        cleaned_key = f"cleaned/{stem}.wav"
        s3.upload_file(output_path, req.bucket, cleaned_key)
        logger.info(f"Uploaded to s3://{req.bucket}/{cleaned_key}")

        return CleanResponse(
            cleaned_bucket=req.bucket,
            cleaned_key=cleaned_key,
            original_key=req.key,
            duration_seconds=round(duration_seconds, 2),
        )

    except Exception as e:
        logger.error(f"Cleaning failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        for p in [input_path, output_path]:
            if os.path.exists(p):
                os.unlink(p)


@app.post("/transcribe")
def transcribe(req: S3Request):
    logger.info(f"Transcribe request: s3://{req.bucket}/{req.key}")

    # Download audio from S3 to temp file
    suffix = Path(req.key).suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = tmp.name

    try:
        s3.download_file(req.bucket, req.key, tmp_path)
        logger.info(f"Downloaded to {tmp_path}")

        # Run Whisper
        segments_iter, info = whisper_model.transcribe(
            tmp_path,
            word_timestamps=True,
            language="en",
            vad_filter=True,
        )

        # Build Transcribe-compatible JSON
        items = []
        all_words = []
        for segment in segments_iter:
            if not segment.words:
                continue
            for w in segment.words:
                word_text = w.word.strip()
                if not word_text:
                    continue
                all_words.append(word_text)
                items.append({
                    "type": "pronunciation",
                    "alternatives": [{
                        "confidence": str(round(w.probability, 4)),
                        "content": word_text,
                    }],
                    "start_time": str(round(w.start, 3)),
                    "end_time": str(round(w.end, 3)),
                })

        full_text = " ".join(all_words)

        result = {
            "jobName": f"local-whisper-{Path(req.key).stem}",
            "accountId": "local",
            "status": "COMPLETED",
            "results": {
                "transcripts": [{"transcript": full_text}],
                "items": items,
                "language_code": "en-US",
            },
        }

        logger.info(f"Transcribed: {len(items)} words, {info.duration:.1f}s")
        return result

    except s3.exceptions.NoSuchKey:
        raise HTTPException(status_code=404, detail=f"S3 key not found: {req.key}")
    except Exception as e:
        logger.error(f"Transcription failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ─── Diarization ───────────────────────────────────────────────────────


@app.post("/diarize")
def diarize(req: S3Request):
    """Download audio from S3, run pyannote speaker diarization."""
    logger.info(f"Diarize request: s3://{req.bucket}/{req.key}")

    suffix = Path(req.key).suffix or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = tmp.name

    try:
        s3.download_file(req.bucket, req.key, tmp_path)
        logger.info(f"Downloaded to {tmp_path}")

        pipeline = get_diarize_pipeline()
        result = pipeline(tmp_path)
        diarization = result.speaker_diarization

        speakers = set()
        segments = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            speakers.add(speaker)
            segments.append({
                "speaker": speaker,
                "start": round(turn.start, 3),
                "end": round(turn.end, 3),
            })

        logger.info(f"Diarized: {len(segments)} turns, {len(speakers)} speakers")
        return {
            "speakers": sorted(speakers),
            "segments": segments,
        }

    except Exception as e:
        logger.error(f"Diarization failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ─── Segmentation ─────────────────────────────────────────────────────


class SegmentRequest(BaseModel):
    bucket: str
    key: str  # cleaned audio key
    transcript: dict  # Whisper JSON (results.items)
    speaker_segments: list[dict]  # from /diarize


@app.post("/segment")
def segment(req: SegmentRequest):
    """Segment audio into training-ready clips, respecting speaker boundaries."""
    logger.info(f"Segment request: s3://{req.bucket}/{req.key}")

    from pydub import AudioSegment

    suffix = Path(req.key).suffix or ".wav"
    stem = Path(req.key).stem
    file_id = stem

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = tmp.name

    try:
        s3.download_file(req.bucket, req.key, tmp_path)
        audio = AudioSegment.from_file(tmp_path)
        logger.info(f"Audio loaded: {len(audio)/1000:.1f}s")

        # Extract words from transcript
        words = []
        for item in req.transcript.get("results", {}).get("items", []):
            if item.get("type") != "pronunciation":
                continue
            alts = item.get("alternatives", [])
            if not alts:
                continue
            words.append({
                "text": alts[0]["content"],
                "start": float(item["start_time"]),
                "end": float(item["end_time"]),
                "confidence": float(alts[0].get("confidence", "0")),
            })

        # Generate segment ID prefix from file content hash
        with open(tmp_path, "rb") as f:
            id_prefix = hashlib.md5(f.read(65536)).hexdigest()[:8]

        # Config
        MIN_DURATION = 3.0
        MAX_DURATION = 15.0
        TARGET_MIN = 5.0
        PAUSE_THRESHOLD = 0.3
        END_BUFFER_MS = 100

        segments_out = []
        seg_index = 0

        # Process each speaker turn
        for spk_seg in req.speaker_segments:
            spk_start = spk_seg["start"]
            spk_end = spk_seg["end"]
            speaker = spk_seg["speaker"]

            # Filter words to this speaker turn (by word midpoint)
            turn_words = [
                w for w in words
                if (w["start"] + w["end"]) / 2 >= spk_start
                and (w["start"] + w["end"]) / 2 <= spk_end
            ]
            if not turn_words:
                continue

            # Find boundaries within this turn
            boundaries = _find_boundaries(turn_words, spk_start, spk_end,
                                          MIN_DURATION, MAX_DURATION, TARGET_MIN, PAUSE_THRESHOLD)

            # Cut audio for each boundary
            for boundary in boundaries:
                b_start = boundary["start"]
                b_end = boundary["end"]
                duration = b_end - b_start

                # Get words in this boundary
                seg_words = [
                    w for w in turn_words
                    if w["start"] >= b_start - 0.05 and w["end"] <= b_end + 0.05
                ]
                seg_text = " ".join(w["text"] for w in seg_words)
                if not seg_text.strip():
                    continue

                # Cut audio
                start_ms = int(b_start * 1000)
                end_ms = int(b_end * 1000) + END_BUFFER_MS
                end_ms = min(end_ms, len(audio))
                seg_audio = audio[start_ms:end_ms]

                # Export to temp file
                segment_id = f"{id_prefix}_{seg_index:05d}"
                seg_path = os.path.join(tempfile.gettempdir(), f"{segment_id}.wav")
                seg_audio.export(seg_path, format="wav")

                # Upload to S3
                s3_key = f"training-segments/{file_id}/{segment_id}.wav"
                s3.upload_file(seg_path, PROCESSED_BUCKET, s3_key)
                os.unlink(seg_path)

                avg_conf = sum(w["confidence"] for w in seg_words) / len(seg_words) if seg_words else 0

                segments_out.append({
                    "segment_id": segment_id,
                    "s3_key": s3_key,
                    "start": round(b_start, 3),
                    "end": round(b_end, 3),
                    "duration": round(duration, 3),
                    "text": seg_text,
                    "speaker": speaker,
                    "word_count": len(seg_words),
                    "avg_word_confidence": round(avg_conf, 4),
                })
                seg_index += 1

        logger.info(f"Segmented: {len(segments_out)} segments from {len(req.speaker_segments)} speaker turns")
        return {"file_id": file_id, "segments": segments_out}

    except Exception as e:
        logger.error(f"Segmentation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _find_boundaries(words, constraint_start, constraint_end,
                     min_dur, max_dur, target_min, pause_thresh):
    """Find segment boundaries within a speaker turn."""
    if not words:
        return []

    boundaries = []
    seg_start = constraint_start
    prev_end = constraint_start

    for i, word in enumerate(words):
        duration = word["end"] - seg_start
        is_last = i == len(words) - 1

        # Check for natural break points
        is_sentence_end = word["text"].rstrip().endswith((".", "!", "?"))
        gap = word["start"] - prev_end if prev_end > 0 else 0
        is_pause = gap > pause_thresh

        should_cut = False
        if duration >= max_dur:
            should_cut = True
        elif duration >= target_min and is_sentence_end:
            should_cut = True
        elif duration >= target_min and is_pause:
            should_cut = True

        if should_cut or is_last:
            seg_end = word["end"]
            seg_duration = seg_end - seg_start
            if seg_duration >= min_dur or is_last:
                boundaries.append({"start": seg_start, "end": seg_end})
            seg_start = words[i + 1]["start"] if not is_last else seg_end

        prev_end = word["end"]

    return boundaries


# ─── Emotion Classification ───────────────────────────────────────────


class EmotionRequest(BaseModel):
    bucket: str
    segments: list[dict]  # [{segment_id, s3_key, text, ...}]


@app.post("/classify-emotions")
def classify_emotions(req: EmotionRequest):
    """Classify emotions for each segment using text (ModernBERT) + audio (emotion2vec)."""
    logger.info(f"Emotion classification for {len(req.segments)} segments")

    text_clf = get_text_emotion_pipeline()
    audio_clf = get_audio_emotion_model()

    results = []
    for seg in req.segments:
        seg_id = seg["segment_id"]
        text = seg.get("text", "")
        s3_key = seg.get("s3_key", "")

        # Text emotion (ModernBERT GoEmotions)
        text_emotion = "neutral"
        text_confidence = 0.0
        if text.strip():
            try:
                text_scores = text_clf(text[:512])[0]  # truncate to model max
                top_text = max(text_scores, key=lambda x: x["score"])
                text_emotion = top_text["label"]
                text_confidence = top_text["score"]
            except Exception as e:
                logger.warning(f"Text emotion failed for {seg_id}: {e}")

        # Audio emotion (emotion2vec)
        audio_emotion = "neutral"
        audio_confidence = 0.0
        if s3_key:
            try:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_f:
                    tmp_audio = tmp_f.name
                s3.download_file(req.bucket, s3_key, tmp_audio)
                emo_result = audio_clf.generate(
                    input=tmp_audio,
                    granularity="utterance",
                    extract_embedding=False,
                )
                if emo_result and emo_result[0].get("scores"):
                    scores = emo_result[0]["scores"]
                    labels = emo_result[0].get("labels", EMOTION2VEC_LABELS)
                    top_idx = scores.index(max(scores))
                    audio_emotion = labels[top_idx]
                    audio_confidence = scores[top_idx]
            except Exception as e:
                logger.warning(f"Audio emotion failed for {seg_id}: {e}")
            finally:
                if os.path.exists(tmp_audio):
                    os.unlink(tmp_audio)

        # Merge: text 40%, audio 60%
        text_tag = GOEMOTION_TO_TAG.get(text_emotion, "neutral")
        audio_tag = EMOTION2VEC_TO_TAG.get(audio_emotion, "neutral")

        if text_tag == audio_tag:
            merged_emotion = text_tag
            merged_confidence = max(text_confidence, audio_confidence)
        elif text_tag == "neutral":
            merged_emotion = audio_tag
            merged_confidence = audio_confidence * 0.9
        elif audio_tag == "neutral":
            merged_emotion = text_tag
            merged_confidence = text_confidence * 0.9
        else:
            # Conflict — prefer audio (60% weight)
            if audio_confidence * 0.6 >= text_confidence * 0.4:
                merged_emotion = audio_tag
                merged_confidence = audio_confidence * 0.6
            else:
                merged_emotion = text_tag
                merged_confidence = text_confidence * 0.4

        results.append({
            "segment_id": seg_id,
            "emotion": merged_emotion,
            "emotion_confidence": round(merged_confidence, 4),
            "text_emotion": text_emotion,
            "text_confidence": round(text_confidence, 4),
            "audio_emotion": audio_emotion,
            "audio_confidence": round(audio_confidence, 4),
        })

        logger.info(f"  {seg_id}: {merged_emotion} ({merged_confidence:.2f}) "
                     f"[text={text_emotion}, audio={audio_emotion}]")

    logger.info(f"Classified {len(results)} segments")
    return {"segments": results}
