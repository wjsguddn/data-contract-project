from celery import Celery
import os

redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')

celery_app = Celery(
    'data_contract_validation',
    broker=redis_url,
    backend=redis_url,
    include=[
        'backend.classification_agent.agent',
        'backend.consistency_agent.agent',
        'backend.report_agent.agent',
        'backend.report_agent.tasks'
    ]
)

# Celery 설정
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Asia/Seoul',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30분
    task_soft_time_limit=25 * 60,  # 25분
)
