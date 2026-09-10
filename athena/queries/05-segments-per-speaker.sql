-- Segments per speaker: count, total duration, avg confidence
SELECT file_id, speaker,
       COUNT(*) AS segment_count,
       ROUND(SUM(duration), 2) AS total_duration,
       ROUND(AVG(avg_word_confidence), 4) AS avg_confidence
FROM robert_mcallister_capstone.training_segments
GROUP BY file_id, speaker
ORDER BY total_duration DESC;
