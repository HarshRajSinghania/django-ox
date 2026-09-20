import json
from io import StringIO

import pytest
from django.core.management import ManagementUtility, call_command
from django.core.management.base import CommandError

from django_ox.models import OxScheduleTick, OxTask

from .contention import CONTENTION, failing, simulated
from .test_prune import make_old_rows, make_task, make_tick, prune


def prune_json(*args):
    out = StringIO()
    error = None
    try:
        call_command("ox_prune", "--format", "json", *args, stdout=out)
    except CommandError as exc:
        error = exc
    raw = out.getvalue()
    return json.loads(raw), error, raw


@pytest.mark.django_db
class TestPruneJson:
    def test_json_reports_deleted_counts_and_no_prose(self):
        make_task(OxTask.Status.SUCCESSFUL, finished_days_ago=8)
        make_tick("a", scheduled_days_ago=8)
        make_tick("a", scheduled_days_ago=1)

        report, error, raw = prune_json()

        assert error is None
        assert raw.strip() == json.dumps(report)
        assert report["queue"] is None
        assert report["statuses"] == [
            OxTask.Status.SUCCESSFUL,
            OxTask.Status.DISCARDED,
        ]
        assert report["task_rows"] == 1
        assert report["tick_rows"] == 1
        assert report["dry_run"] is False
        assert OxTask.objects.count() == 0
        assert OxScheduleTick.objects.count() == 1

    def test_json_dry_run_uses_the_same_count_keys(self):
        make_task(OxTask.Status.SUCCESSFUL, finished_days_ago=8, queue_name="emails")
        make_tick("a", scheduled_days_ago=8)
        make_tick("a", scheduled_days_ago=1)

        report, error, raw = prune_json("--queue", "emails", "--dry-run")

        assert error is None
        assert raw.strip() == json.dumps(report)
        assert report["queue"] == "emails"
        assert report["statuses"] == [
            OxTask.Status.SUCCESSFUL,
            OxTask.Status.DISCARDED,
        ]
        assert report["task_rows"] == 1
        assert report["tick_rows"] == 1
        assert report["dry_run"] is True
        assert OxTask.objects.count() == 1
        assert OxScheduleTick.objects.count() == 2

    def test_format_text_is_the_default_output(self):
        make_task(OxTask.Status.SUCCESSFUL, finished_days_ago=8)
        default = prune()
        make_task(OxTask.Status.SUCCESSFUL, finished_days_ago=8)
        explicit = prune("--format", "text")

        assert default.startswith("Deleted 1 ")
        assert explicit.startswith("Deleted 1 ")
        assert "{" not in default
        assert "{" not in explicit


@pytest.mark.django_db(transaction=True)
class TestPruneJsonContention:
    ARGS = ("--include-failed", "--batch-size=2")
    DELETE = "DELETE FROM DJANGO_OX_OXTASK"

    @pytest.mark.parametrize("kind", CONTENTION)
    def test_json_contention_prints_committed_counts_and_exits_non_zero(self, kind):
        make_old_rows(5, OxTask.Status.FAILED)

        with failing(self.DELETE, lambda: simulated(kind), lambda n: n >= 2):
            report, error, raw = prune_json(*self.ARGS)

        assert isinstance(error, CommandError)
        assert "Stopped after deleting 2 " in str(error)
        assert raw.strip() == json.dumps(report)
        assert report["task_rows"] == 2
        assert report["tick_rows"] == 0
        assert report["dry_run"] is False
        assert report["statuses"] == [
            OxTask.Status.SUCCESSFUL,
            OxTask.Status.DISCARDED,
            OxTask.Status.FAILED,
            OxTask.Status.LOST,
        ]
        assert OxTask.objects.count() == 3

    @pytest.mark.parametrize("kind", CONTENTION)
    def test_json_contention_exits_non_zero_from_the_command_line(self, kind, capsys):
        make_old_rows(5, OxTask.Status.FAILED)
        argv = [
            "manage.py",
            "ox_prune",
            *self.ARGS,
            "--format",
            "json",
            "--skip-checks",
        ]

        with (
            failing(self.DELETE, lambda: simulated(kind), lambda n: n >= 2),
            pytest.raises(SystemExit) as info,
        ):
            ManagementUtility(argv).execute()

        captured = capsys.readouterr()
        assert info.value.code == 1
        report = json.loads(captured.out)
        assert report["task_rows"] == 2
        assert report["tick_rows"] == 0
        assert "Stopped after deleting 2 " in captured.err
        assert OxTask.objects.count() == 3
