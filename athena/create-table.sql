CREATE EXTERNAL TABLE robert_mcallister_capstone.transcripts (
  file_id STRING,
  source_file STRING,
  transcript_text STRING,
  word_count INT,
  duration_seconds DOUBLE,
  language_code STRING,
  words ARRAY<STRUCT<
    word: STRING,
    start_time: DOUBLE,
    end_time: DOUBLE,
    confidence: DOUBLE
  >>,
  segments ARRAY<STRUCT<
    speaker: STRING,
    start_time: DOUBLE,
    end_time: DOUBLE,
    text: STRING
  >>,
  processed_at STRING
)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
LOCATION 's3://robert-mcallister-processed/transcripts/';
