# Glue Data Catalog (used by Athena)

resource "aws_glue_catalog_database" "capstone" {
  name = "robert_mcallister_capstone"
}

resource "aws_glue_catalog_table" "transcripts" {
  name          = "transcripts"
  database_name = aws_glue_catalog_database.capstone.name

  table_type = "EXTERNAL_TABLE"

  parameters = {
    "classification" = "json"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.processed.id}/transcripts/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
    }

    columns {
      name = "file_id"
      type = "string"
    }
    columns {
      name = "source_file"
      type = "string"
    }
    columns {
      name = "transcript_text"
      type = "string"
    }
    columns {
      name = "word_count"
      type = "int"
    }
    columns {
      name = "duration_seconds"
      type = "double"
    }
    columns {
      name = "language_code"
      type = "string"
    }
    columns {
      name = "words"
      type = "array<struct<word:string,start_time:double,end_time:double,confidence:double>>"
    }
    columns {
      name = "segments"
      type = "array<struct<speaker:string,start_time:double,end_time:double,text:string>>"
    }
    columns {
      name = "processed_at"
      type = "string"
    }
  }
}

resource "aws_glue_catalog_table" "training_segments" {
  name          = "training_segments"
  database_name = aws_glue_catalog_database.capstone.name

  table_type = "EXTERNAL_TABLE"

  parameters = {
    "classification" = "json"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.processed.id}/segment-metadata/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
    }

    columns {
      name = "file_id"
      type = "string"
    }
    columns {
      name = "segment_id"
      type = "string"
    }
    columns {
      name = "s3_key"
      type = "string"
    }
    columns {
      name = "start"
      type = "double"
    }
    columns {
      name = "end"
      type = "double"
    }
    columns {
      name = "duration"
      type = "double"
    }
    columns {
      name = "text"
      type = "string"
    }
    columns {
      name = "speaker"
      type = "string"
    }
    columns {
      name = "word_count"
      type = "int"
    }
    columns {
      name = "avg_word_confidence"
      type = "double"
    }
    columns {
      name = "emotion"
      type = "string"
    }
    columns {
      name = "emotion_confidence"
      type = "double"
    }
    columns {
      name = "text_emotion"
      type = "string"
    }
    columns {
      name = "audio_emotion"
      type = "string"
    }
  }
}
