CREATE EXTERNAL TABLE robert_mcallister_capstone.training_segments (
  file_id STRING,
  segment_id STRING,
  s3_key STRING,
  `start` DOUBLE,
  `end` DOUBLE,
  duration DOUBLE,
  text STRING,
  speaker STRING,
  word_count INT,
  avg_word_confidence DOUBLE,
  emotion STRING,
  emotion_confidence DOUBLE,
  text_emotion STRING,
  audio_emotion STRING
)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
LOCATION 's3://robert-mcallister-processed/segment-metadata/';
