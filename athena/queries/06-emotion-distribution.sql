-- Emotion distribution across all segments
SELECT emotion,
       COUNT(*) AS segment_count,
       ROUND(AVG(emotion_confidence), 4) AS avg_confidence,
       ROUND(AVG(duration), 2) AS avg_duration
FROM robert_mcallister_capstone.training_segments
GROUP BY emotion
ORDER BY segment_count DESC;
