# Permissions Matrix

| Role | review_source | select_topic | schedule_topic | generate_brief | review_evidence | approve_brief | render | generate_tts | generate_platform_package | export_audit |
|---|---|---|---|---|---|---|---|---|---|---|
| admin | allow | allow | allow | allow | allow | allow | allow | allow | allow | allow |
| editor | deny | allow | allow | allow | deny | deny | deny | deny | deny | deny |
| reviewer | allow | deny | deny | deny | allow | allow | deny | deny | deny | allow |
| producer | deny | deny | deny | deny | deny | deny | allow | allow | allow | deny |
| viewer | deny | deny | deny | deny | deny | deny | deny | deny | deny | deny |
