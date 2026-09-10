-- Low-confidence words (potential transcription errors)
SELECT file_id, w.word, ROUND(w.confidence, 4) AS confidence,
       w.start_time, w.end_time
FROM robert_mcallister_capstone.transcripts
CROSS JOIN UNNEST(words) AS t(w)
WHERE w.confidence < 0.5
ORDER BY w.confidence ASC;
