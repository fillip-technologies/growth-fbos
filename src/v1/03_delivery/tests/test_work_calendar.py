"""Working time from a working calendar (services/work_calendar.py)."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from services.work_calendar import calendar_from

IST = ZoneInfo("Asia/Kolkata")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri")


def calendar(hours=(("09:00", "18:00"),), days=WEEKDAYS, holidays=()):
    return calendar_from({
        "timezone": "Asia/Kolkata",
        "weekly_hours": {day: [list(r) for r in hours] for day in days},
        "holidays": [{"date": d, "is_half_day": half} for d, half in holidays],
    })


def at(day: int, hour: int, minute: int = 0) -> datetime:
    """A moment in India in October 2026 (the 5th and the 12th are Mondays)."""
    return datetime(2026, 10, day, hour, minute, tzinfo=IST)


def test_time_out_of_hours_doesnt_count():
    week = calendar()
    # Friday 17:00 plus two working hours: one on Friday, one on Monday morning.
    assert week.add_minutes(at(9, 17), 120) == at(12, 10)
    assert week.minutes_between(at(9, 17), at(12, 10)) == 120
    # From a Saturday: the clock starts on Monday at nine.
    assert week.add_minutes(at(10, 8), 30) == at(12, 9, 30)
    assert week.minutes_between(at(10, 8), at(11, 23)) == 0


def test_a_break_between_ranges_doesnt_count():
    with_lunch = calendar(hours=(("09:30", "13:30"), ("14:30", "18:30")))
    assert with_lunch.add_minutes(at(5, 13), 60) == at(5, 15)
    assert with_lunch.minutes_between(at(5, 13), at(5, 15)) == 60


def test_holidays_and_half_days():
    monday_off = calendar(holidays=[("2026-10-12", False)])
    assert monday_off.add_minutes(at(9, 17), 120) == at(13, 10)
    # A half day keeps the morning: 09:00-13:30 of a 09:00-18:00 day.
    monday_half = calendar(holidays=[("2026-10-12", True)])
    assert monday_half.add_minutes(at(9, 17), 120) == at(12, 10)
    assert monday_half.add_minutes(at(12, 9), 600) == at(13, 14, 30)  # 270 on Monday, 330 on Tuesday
    assert monday_half.minutes_between(at(12, 9), at(12, 18)) == 270


def test_adding_and_measuring_agree_across_weeks():
    week = calendar()
    start = at(7, 11, 15)
    for minutes in (1, 59, 540, 541, 2000, 9000):
        assert week.minutes_between(start, week.add_minutes(start, minutes)) == minutes


def test_a_calendar_without_working_time_or_a_known_zone_isnt_used():
    assert calendar(days=()) is None
    assert calendar_from({"timezone": "Mars/Olympus", "weekly_hours": {"mon": [["09:00", "18:00"]]}}) is None
    # Malformed ranges are left out rather than failing.
    odd = calendar_from({"timezone": "UTC", "weekly_hours": {"mon": [["18:00", "09:00"], ["bad"], ["09:00", "10:00"]]}})
    monday = datetime(2026, 10, 5, tzinfo=timezone.utc)
    assert odd.minutes_between(monday, monday + timedelta(days=1)) == 60
    assert odd.add_minutes(monday + timedelta(hours=9, minutes=30), 60) == monday + timedelta(days=7, hours=9, minutes=30)
