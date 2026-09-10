-- Average word confidence per file
SELECT file_id,
       word_count,
       ROUND(REDUCE(words, CAST(0.0 AS DOUBLE),
         (s, w) -> s + w.confidence,
         s -> s / word_count), 4) AS avg_confidence
FROM robert_mcallister_capstone.transcripts;
