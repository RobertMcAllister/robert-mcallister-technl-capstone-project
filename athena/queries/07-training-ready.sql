-- Training-ready segments: high confidence, good duration, with emotion labels
SELECT file_id, segment_id, speaker, emotion,
       ROUND(duration, 2) AS duration,
       ROUND(avg_word_confidence, 4) AS confidence,
       text
FROM robert_mcallister_capstone.training_segments
WHERE avg_word_confidence >= 0.7
  AND duration BETWEEN 5.0 AND 15.0
ORDER BY avg_word_confidence DESC;
