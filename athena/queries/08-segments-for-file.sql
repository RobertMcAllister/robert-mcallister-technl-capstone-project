-- All segments and transcriptions for a specific file
SELECT segment_id, speaker, emotion,
       ROUND(duration, 2) AS duration,
       ROUND(avg_word_confidence, 4) AS confidence,
       text
FROM robert_mcallister_capstone.training_segments
WHERE file_id = 'BigA_Sample_1min'
ORDER BY "start" ASC;
