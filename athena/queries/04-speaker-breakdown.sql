-- Speaker breakdown: who spoke, how long, what they said
SELECT file_id, s.speaker,
       ROUND(s.end_time - s.start_time, 2) AS duration_seconds,
       s.text
FROM robert_mcallister_capstone.transcripts
CROSS JOIN UNNEST(segments) AS t(s)
ORDER BY s.start_time;
