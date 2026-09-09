from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import create_app
from collector import CollectionResult
from main import create_scheduler
from pipeline import NewsPipeline
from repositories import MemoryRepository


class EmptyCollector:
    async def collect(self):
        return CollectionResult()


class RecordingWorker:
    def __init__(self):
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1

    async def stop(self):
        self.stopped += 1


class RecordingScheduler:
    def __init__(self):
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1

    def shutdown(self, wait=False):
        del wait
        self.stopped += 1


def settings():
    return SimpleNamespace(
        admin_password="1234",
        session_secret="test-secret-with-enough-length",
        cookie_secure=False,
    )


def test_lifespan_starts_and_stops_worker_and_scheduler():
    worker = RecordingWorker()
    scheduler = RecordingScheduler()
    repository = MemoryRepository()
    pipeline = NewsPipeline(repository, EmptyCollector())
    app = create_app(
        settings(),
        repository,
        pipeline,
        worker=worker,
        scheduler=scheduler,
    )

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert worker.started == 1
        assert scheduler.started == 1

    assert worker.stopped == 1
    assert scheduler.stopped == 1


class RecordingContentRunner:
    async def run_slot(self, slot, scheduled_for=None):
        del slot, scheduled_for


def test_scheduler_registers_exactly_the_six_content_slots_without_publisher():
    scheduler = create_scheduler(RecordingContentRunner())
    ids = {job.id for job in scheduler.get_jobs()}

    assert ids == {
        "content_10_girisim",
        "content_12_ai",
        "content_14_teknoloji",
        "content_16_ai",
        "content_18_yazilim",
        "content_20_girisim",
    }
    assert "publisher_job" not in ids
