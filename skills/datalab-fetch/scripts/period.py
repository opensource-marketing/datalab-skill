"""기간 표현을 BASE_YM 두 개로 바꾸고, 지표별 수록 시점을 읽는 계층.

초보자가 가장 자주 걸려 넘어지는 곳이 기간이다. 두 가지 이유가 있다.

1. 데이터랩은 YYYYMM 여섯 자리를 요구한다. "2024", "2024-01", "작년"은
   그대로 넣으면 빈 배열이 온다.
2. 지표마다 데이터가 들어오는 시점이 다르다. 지역 방문자 수도 관광사업체
   수도 지난달까지 있지만, 외국인 환자 수와 MICE 개최건수는 연 단위라
   두 해 가까이 뒤처진다(2026-08 기준 2024년까지). 아직 발표되지 않은 달을
   물으면 오류가 아니라 **빈 배열**이 온다 — 그래서 "이 지역에는
   사업체가 없다"로 오해하기 쉽다.

이 모듈은 1번을 resolve()로, 2번을 latest()/explain_gap()으로 다룬다.
수록 시점 표(catalog/coverage.yaml)는 probe_coverage.py가 실호출로
만든다. 이 모듈 자체는 네트워크를 쓰지 않는다.
"""
import datetime
import pathlib
import re

import yaml

COVERAGE_PATH = (pathlib.Path(__file__).resolve().parents[1]
                 / "catalog" / "coverage.yaml")
YM = re.compile(r"^\d{6}$")
_coverage_cache = None


class PeriodError(ValueError):
    """기간 표현을 이해하지 못했을 때. 사용자 입력이 원인이다."""


def load_coverage(path=None):
    """지표별 수록 시점 표를 읽는다. 인자가 없으면 결과를 캐시한다."""
    global _coverage_cache
    if path is not None:
        return yaml.safe_load(pathlib.Path(path).read_text()) or {}
    if _coverage_cache is None:
        if COVERAGE_PATH.exists():
            _coverage_cache = yaml.safe_load(COVERAGE_PATH.read_text()) or {}
        else:
            _coverage_cache = {}
    return _coverage_cache


def latest(qid, coverage=None):
    """그 지표에 값이 있는 마지막 기준월(YYYYMM). 모르면 None.

    연 단위 지표는 그 해 12월로 환산해 돌려준다 — 호출자가 월과 연을
    나눠 다룰 필요가 없게 하기 위해서다.
    """
    entry = (coverage if coverage is not None else load_coverage()).get(qid)
    if not entry:
        return None
    value = entry.get("latest")
    if not value:
        return None
    value = str(value)
    if len(value) == 4:
        return value + "12"
    return value if YM.match(value) else None


def at_anchor(qid, coverage=None):
    """그 지표의 수록 시점이 '확인한 하한'인가.

    프로브는 실행일의 지난달까지만 물어본다. 그 마지막 달에 값이 있으면
    거기서 멈추므로, 기록된 latest 는 "여기가 끝"이 아니라 "여기까지는
    확인했다"는 뜻이 된다. 실제로 101개 중 70개가 그렇다. 이 둘을
    구분하지 않으면 표가 낡을수록 있는 데이터를 없다고 자르게 된다.
    """
    entry = (coverage if coverage is not None else load_coverage()).get(qid)
    return bool(entry and entry.get("상한도달"))


def ceiling(qid, coverage=None, today=None):
    """clamp 가 쓰는 상한. 모르면 None.

    수록 시점이 확인된 상한이면(그 뒤를 물어봤는데 없었다) 그대로 쓴다.
    확인한 하한일 뿐이면(프로브가 거기서 멈췄다) 지난달까지 열어 둔다 —
    그 사이에 새 달이 나왔을 수 있고, 나오지 않았다면 빈 배열이 올 뿐
    우리가 지어낸 상한으로 자르는 것보다 낫다.
    """
    end = latest(qid, coverage)
    if end is None:
        return None
    if at_anchor(qid, coverage):
        return max(end, _last_month(today))
    return end


def explain_gap(qid, ym1, ym2, coverage=None, *, today=None):
    """빈 결과가 '아직 안 나온 달'이어서인지 설명한다. 아니면 None.

    이 함수가 문장을 돌려준다는 것은 "데이터가 없다"가 아니라
    "아직 발표되지 않았다"는 뜻이다. 둘은 사업 판단에서 정반대다.
    """
    end = ceiling(qid, coverage, today=today)
    if end is None or not ym2:
        return None
    if ym2 <= end:
        return None
    if ym1 and ym1 > end:
        return (f"이 지표는 {_ko(end)}까지 확인되어 있습니다. "
                f"요청 기간({_ko(ym1)}~{_ko(ym2)})은 전부 그 뒤라 "
                f"값이 없습니다.")
    return (f"이 지표는 {_ko(end)}까지 확인되어 있습니다. "
            f"{_ko(end)} 이후는 아직 나오지 않았습니다.")


def clamp(qid, ym1, ym2, coverage=None, *, today=None):
    """요청 기간을 그 지표가 실제로 가진 마지막 달까지로 줄인다.

    (ym1, ym2, 조정) 을 돌려준다. 줄일 것이 없으면 조정은 None이고,
    요청 기간이 통째로 수록 시점 뒤라면 (None, None, 조정) 이다 —
    부를 필요조차 없다는 뜻이다.

    조정은 {"요청": 요청한 끝, "수록": 지표의 마지막 달, "부름": 실제로
    부른 끝 또는 None} 이다. 문장이 아니라 값으로 돌려주는 이유는,
    지표 열넷이 모두 같은 이유로 줄어들 때 같은 문장 열넷을 늘어놓지
    않고 한 줄로 묶기 위해서다. 문장은 note_text()가 만든다.

    왜 줄이는가. 시점 재고 지표(관광사업체 수, 객실 수)는 BASE_YM2
    하나로 시점을 정하는데, 아직 발표되지 않은 달을 넣으면 빈 배열이
    온다. 사용자는 "2026년"이라고 말했을 뿐인데 사업체가 0개인 것처럼
    보인다.
    """
    end = ceiling(qid, coverage, today=today)
    if end is None or not ym2 or ym2 <= end:
        return ym1, ym2, None
    if ym1 and ym1 > end:
        return None, None, {"요청": ym2, "수록": end, "부름": None}
    return ym1, end, {"요청": ym2, "수록": end, "부름": end}


def note_text(note):
    """clamp()가 돌려준 조정 하나를 사람이 읽는 문장으로 만든다."""
    if not note:
        return None
    if note["부름"] is None:
        return (f"요청 기간이 모두 수록 시점({_ko(note['수록'])}) 뒤라 "
                f"부르지 않았습니다.")
    return (f"{_ko(note['요청'])}까지 요청했지만 {_ko(note['수록'])}까지만 "
            f"확인되어 그때까지로 줄여 불렀습니다.")


def summarize_notes(notes):
    """조정 여럿을 묶어 요약 문장 목록으로 만든다.

    같은 이유로 줄어든 지표가 열넷이면 문장도 열넷이 아니라 하나여야
    한다. 끝이 서로 다른 것만 따로 나눈다.
    """
    if not notes:
        return []
    groups = {}
    for qid, note in notes.items():
        if not note:
            continue
        groups.setdefault((note["요청"], note["수록"], note["부름"]),
                          []).append(qid)
    lines = []
    for (asked, have, called), qids in sorted(groups.items()):
        count = len(qids)
        if called is None:
            lines.append(
                f"지표 {count}개는 요청 기간이 모두 확인된 시점"
                f"({_ko(have)}) 뒤라 부르지 않았습니다.")
        else:
            lines.append(
                f"{_ko(asked)}까지 요청했지만 지표 {count}개는 "
                f"{_ko(have)}까지만 확인되어 그때까지로 줄여 불렀습니다.")
    return lines


def _ko(ym):
    return f"{ym[:4]}-{ym[4:]}" if len(ym) == 6 else str(ym)


def shift(ym, months):
    """기준월을 months 만큼 옮긴다. 음수면 과거로."""
    if not YM.match(str(ym)):
        raise PeriodError(f"YYYYMM 형식이 아닙니다: {ym}")
    total = int(ym[:4]) * 12 + (int(ym[4:]) - 1) + months
    return f"{total // 12:04d}{total % 12 + 1:02d}"


def span(ym1, ym2):
    """두 기준월 사이의 개월 수(양끝 포함)."""
    for value in (ym1, ym2):
        if not YM.match(str(value)):
            raise PeriodError(f"YYYYMM 형식이 아닙니다: {value}")
    return ((int(ym2[:4]) - int(ym1[:4])) * 12
            + int(ym2[4:]) - int(ym1[4:]) + 1)


def _anchor(today, anchor):
    """'최근'의 끝이 되는 마지막 달을 고른다.

    기본값은 지난달이다. 이번 달 데이터는 어떤 지표에도 아직 없다.
    호출자가 지표의 수록 시점(anchor)을 알면 그쪽이 더 정확하다.
    """
    if anchor:
        if not YM.match(str(anchor)):
            raise PeriodError(f"anchor 는 YYYYMM 이어야 합니다: {anchor}")
        return anchor
    return _last_month(today)


def _last_month(today):
    today = today or datetime.date.today()
    return shift(f"{today.year:04d}{today.month:02d}", -1)


_RANGE = re.compile(r"^(\d{6})\s*[-~]\s*(\d{6})$")
_YEAR = re.compile(r"^(\d{4})$")
_HALF = re.compile(r"^(\d{4})\s*(상|하)반기$")
_QUARTER = re.compile(r"^(\d{4})\s*(?:Q|[1-4]분기|q)(\d)?$", re.I)
_RECENT = re.compile(r"^(?:최근|last[:\s]*)\s*(\d+)\s*(개월|달|년|년치|months?|m|y)?$",
                     re.I)
_DASHED = re.compile(r"^(\d{4})[-./](\d{1,2})$")


def resolve(spec, *, today=None, anchor=None):
    """사람이 쓰는 기간 표현을 (ym1, ym2)로 바꾼다.

    받아들이는 형태:
      202401-202412 / 202401~202412 / 2024-01~2024-12
      2024 / 2024년 / 24년  → 202401-202412
      2024년 1월            → 202401
      2024상반기 / 2024하반기
      2024Q3                → 202407-202409
      최근12개월 / 최근 1년 / last:12
      올해 / 작년 / 재작년 / 지난달
      작년 상반기 / 올해 4분기 (상대 연도 + 반기·분기)

    '최근'과 '올해'의 끝은 anchor(지표의 수록 시점)가 있으면 그것,
    없으면 지난달이다.
    """
    if spec is None:
        raise PeriodError("기간이 비어 있습니다.")
    text = str(spec).strip().replace(" ", "")
    if not text:
        raise PeriodError("기간이 비어 있습니다.")

    # 사람은 "2024년 강릉 방문자"라고 말한다. 에이전트가 그 말을 그대로
    # 옮기면 "기간을 이해하지 못했습니다"가 나왔다 — 한국어에서 연도에
    # "년"을 붙이는 것은 기본형에 가깝다. 여섯 자리 연월(202401)은
    # 건드리지 않도록 네 자리 뒤의 "년"만 벗긴다.
    # "2024년 1월"은 사람이 가장 흔히 쓰는 표기다. 먼저 연월을 붙여
    # 여섯 자리로 만든 뒤에 "년"만 남은 것을 벗긴다 — 순서를 바꾸면
    # "2024년 1월"이 "2024 1월"이 되어 어느 쪽도 알아보지 못한다.
    text = re.sub(r"(?<!\d)(\d{4})년(\d{1,2})월",
                  lambda m: f"{m.group(1)}{int(m.group(2)):02d}", text)
    text = re.sub(r"(?<!\d)(\d{4})년", r"\1", text)
    # 두 자리 연도도 받는다. 데이터랩 데이터는 2018~2026이라
    # "24년"을 1924로 읽을 여지가 없다.
    text = re.sub(r"(?<!\d)(\d{2})년", r"20\1", text)
    if re.fullmatch(r"\d{2}", text):
        text = "20" + text

    match = _RANGE.match(text)
    if match:
        return _ordered(match.group(1), match.group(2))

    if "~" in text or "-" in text:
        parts = re.split(r"[~]|(?<=\d{4}[-./]\d{2})-", text)
        if len(parts) == 2 and all(_DASHED.match(p) or YM.match(p)
                                   for p in parts):
            return _ordered(*(_from_dashed(p) for p in parts))
        # "2024~2025"는 두 해를 통째로 말하는 것이다. 월까지 적으라고
        # 되묻는 것보다 1월부터 12월까지로 읽는 편이 사람의 뜻에 맞다.
        해들 = re.split(r"[~-]", text)
        if len(해들) == 2 and all(_YEAR.fullmatch(h) for h in 해들):
            시작, 끝 = _ordered(f"{해들[0]}01", f"{해들[1]}01")
            return 시작, f"{끝[:4]}12"

    # 한 달만 주는 경우에도 _ordered 를 태운다. 여기를 건너뛰면
    # "202413"이 그대로 통과해 빈 배열을 부르고, 리포트에는 다시
    # "데이터없음"이 찍힌다 — 이 모듈이 없애려던 바로 그 오독이다.
    if YM.match(text):
        return _ordered(text, text)

    match = _DASHED.match(text)
    if match:
        one = _from_dashed(text)
        return _ordered(one, one)

    match = _YEAR.match(text)
    if match:
        year = match.group(1)
        return f"{year}01", f"{year}12"

    match = _HALF.match(text)
    if match:
        year, half = match.group(1), match.group(2)
        return (f"{year}01", f"{year}06") if half == "상" else (f"{year}07",
                                                                f"{year}12")

    match = _QUARTER.match(text)
    if match:
        year = match.group(1)
        digits = re.findall(r"\d", text[4:])
        if not digits:
            raise PeriodError(f"분기를 읽지 못했습니다: {spec}")
        quarter = int(digits[0])
        if not 1 <= quarter <= 4:
            raise PeriodError(f"분기는 1~4 여야 합니다: {spec}")
        start = (quarter - 1) * 3 + 1
        return f"{year}{start:02d}", f"{year}{start + 2:02d}"

    end = _anchor(today, anchor)

    match = _RECENT.match(text)
    if match:
        count = int(match.group(1))
        if count < 1:
            raise PeriodError(f"기간이 1 이상이어야 합니다: {spec}")
        unit = (match.group(2) or "개월").lower()
        months = count * 12 if unit in ("년", "년치", "y") else count
        return shift(end, -(months - 1)), end

    # 달력 낱말은 달력이 정한다. 지표의 수록 시점(anchor)으로 연도를
    # 밀면 "작년"이라고 말한 사용자에게 재작년 값을 보여 주게 된다.
    # anchor 는 "올해"의 **끝**만 당긴다.
    this_year = (today or datetime.date.today()).year
    if text in ("올해", "금년", "이번년", "이번해"):
        start = f"{this_year}01"
        stop = min(end, f"{this_year}12")
        if stop < start:
            raise PeriodError(
                f"{this_year}년 데이터는 아직 없습니다. "
                f"기준으로 삼은 마지막 달은 {_ko(end)}입니다.")
        return start, stop
    if text in ("작년", "전년", "지난해"):
        year = this_year - 1
        return f"{year}01", f"{year}12"
    if text in ("재작년", "그제년"):
        year = this_year - 2
        return f"{year}01", f"{year}12"

    # 이번 달은 어떤 지표에도 없다. 그렇다고 "기간을 이해하지
    # 못했습니다"라고 하면 사용자는 자기 표기가 틀린 줄 알고 다른
    # 말로 바꿔 가며 헤맨다. 알아듣고 없다고 말한다.
    if text in ("이번달", "금월", "당월", "이달", "이번월"):
        마지막 = _last_month(today)
        raise PeriodError(
            f"이번 달 데이터는 아직 없습니다. 가장 최근은 "
            f"{_ko(마지막)}입니다 — '지난달'로 다시 실행하세요.")

    # "지난달"은 수록 시점을 묻는 말이다 — 월 단위 지표의 상당수가
    # 지난달까지만 나와 있다.
    if text in ("지난달", "저번달", "전월"):
        last = shift(_last_month(today), 0)
        return last, last

    # "작년 상반기"는 "작년"만큼 자연스럽다. 상대 연도를 숫자로 바꾼 뒤
    # 이미 있는 반기·분기 처리에 넘긴다.
    #
    # **연도 뒤에 "년"을 붙여 넘긴다.** 숫자만 붙이면 "작년12월"이
    # "202512월"이 되어 어느 규칙에도 걸리지 않는다 — "작년 상반기"는
    # 되는데 "작년 12월"만 안 되는 구멍이 그래서 생겼다. "2025년12월"로
    # 만들면 위쪽 정규화가 "202512"로 접어 준다.
    #
    # "올"은 맨 뒤에 둔다. 앞에 두면 "올해4분기"가 "올"로 먼저 걸려
    # 남은 말이 "해4분기"가 된다.
    상대 = {"올해": 0, "금년": 0, "이번년": 0, "이번해": 0,
            "작년": 1, "전년": 1, "지난해": 1,
            "재작년": 2, "그제년": 2, "올": 0}
    for 낱말, 뒤로 in 상대.items():
        if text.startswith(낱말) and len(text) > len(낱말):
            남은 = text[len(낱말):]
            return resolve(f"{this_year - 뒤로}년{남은}",
                           today=today, anchor=anchor)

    raise PeriodError(
        f"기간을 이해하지 못했습니다: {spec}\n"
        f"  이렇게 쓸 수 있습니다: 2024 / 2024년 1월 / 2024상반기 / "
        f"2024Q3 / 202401-202412 / 최근12개월 / 작년 / 작년 상반기 / "
        f"올해 / 지난달")


def _from_dashed(text):
    if YM.match(text):
        return text
    match = _DASHED.match(text)
    return f"{match.group(1)}{int(match.group(2)):02d}"


def _ordered(ym1, ym2):
    for value in (ym1, ym2):
        if not YM.match(value):
            raise PeriodError(f"YYYYMM 형식이 아닙니다: {value}")
        month = int(value[4:])
        if not 1 <= month <= 12:
            raise PeriodError(f"월이 1~12 범위를 벗어났습니다: {value}")
    if ym1 > ym2:
        raise PeriodError(f"시작({ym1})이 종료({ym2})보다 나중입니다.")
    return ym1, ym2


HELP = ("기간. 2024 / 2024년 1월 / 2024상반기 / 2024Q3 / "
        "202401-202412 / 최근12개월 / 작년 / 작년 상반기 / 올해 / 지난달")


def add_arguments(parser):
    """--period 와 --from/--to 를 한꺼번에 붙인다.

    두 가지를 다 두는 이유. --from/--to 는 정확하지만 초보자는 데이터가
    언제까지 있는지 모른다. --period 는 "작년"이라고 쓰면 되지만 정확한
    구간을 지정할 수 없다. 섞어 쓰면 어느 쪽이 이겼는지 알 수 없으므로
    from_args()가 거부한다.
    """
    parser.add_argument("--period", default=None, metavar="기간", help=HELP)
    parser.add_argument("--from", dest="ym1", default=None, metavar="YYYYMM",
                        help="시작 기준월")
    parser.add_argument("--to", dest="ym2", default=None, metavar="YYYYMM",
                        help="종료 기준월")


def from_args(args, *, default=None, max_months=None, anchor=None,
              allow_open_range=False):
    """--period / --from / --to 에서 (ym1, ym2)를 만든다.

    default 는 (ym1, ym2) 짝이다. 아무것도 주지 않았을 때 쓴다.
    문제가 있으면 PeriodError 를 던진다 — 메시지를 그대로 보여 주면 된다.

    allow_open_range 는 임의 조회용이다. 시점 재고 지표는 BASE_YM2 하나로
    시점을 정하므로 `--from` 없이 `--to` 만 주는 것이 정상이고, 기간을
    아예 안 주는 것도 정상이다. 리포트 스킬에서는 켜지 않는다.
    """
    spec = getattr(args, "period", None)
    ym1, ym2 = getattr(args, "ym1", None), getattr(args, "ym2", None)

    if spec and (ym1 or ym2):
        raise PeriodError(
            "--period 와 --from/--to 를 함께 쓸 수 없습니다. "
            "하나만 고르세요.")

    if spec:
        ym1, ym2 = resolve(spec, anchor=anchor)
    elif ym1 or ym2:
        if allow_open_range:
            return ym1, ym2
        if not (ym1 and ym2):
            missing = "--to" if ym1 else "--from"
            raise PeriodError(
                f"{missing} 가 빠졌습니다. --from 과 --to 는 함께 씁니다. "
                f"한쪽만 알면 --period 를 쓰세요 (예: --period 작년)")
        ym1, ym2 = _ordered(ym1, ym2)
    elif default:
        ym1, ym2 = default
    elif allow_open_range:
        return None, None
    else:
        raise PeriodError(
            "기간을 정해 주세요. --period 작년 처럼 쓰거나 "
            "--from 202401 --to 202412 처럼 씁니다.\n"
            f"  --period 에 쓸 수 있는 것: {HELP}")

    if max_months and span(ym1, ym2) > max_months:
        raise PeriodError(
            f"월 단위 조회는 최대 {max_months}개월입니다. "
            f"요청 기간은 {span(ym1, ym2)}개월입니다.")
    return ym1, ym2


def rows(query=None, coverage=None):
    """수록 시점 표를 (qid, 이름, latest, 카탈로그, 사유) 줄로 돌려준다.

    query 가 있으면 qid·이름에 그 낱말이 들어간 것만 남긴다.
    """
    table = coverage if coverage is not None else load_coverage()
    needles = [t.lower() for t in str(query or "").split() if t]
    out = []
    for qid, entry in sorted(table.items()):
        name = str(entry.get("이름") or "")
        blob = (qid + " " + name).lower()
        if needles and not all(n in blob for n in needles):
            continue
        out.append((qid, name, latest(qid, table),
                    entry.get("카탈로그") or "", entry.get("사유") or ""))
    return out


def _main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(
        description="지표별 데이터 수록 시점을 보고 기간 표현을 풀어 본다")
    sub = parser.add_subparsers(dest="mode", required=True)

    show = sub.add_parser("show", help="지표별 수록 시점 표를 본다")
    show.add_argument("query", nargs="*", help="지표 이름이나 qid의 일부")

    last = sub.add_parser("latest", help="지표 하나의 마지막 수록 월")
    last.add_argument("qid")

    parse = sub.add_parser("parse", help="기간 표현을 YYYYMM 둘로 풀어 본다")
    parse.add_argument("spec")
    parse.add_argument("--anchor")

    args = parser.parse_args(argv)

    if args.mode == "show":
        found = rows(" ".join(args.query))
        if not found:
            # 이 표를 채우는 도구는 개발 전용이라 배포본에는 없다 —
            # 배포본은 표가 이미 채워진 채로 나간다. 없는 파일을
            # 부르라고 안내하는 대신 사실을 그대로 적는다.
            print("해당하는 지표가 없습니다. 검색어를 바꿔 보세요. "
                  "표 자체가 비어 있다면 datalab-fetch 설치를 다시 "
                  "확인하세요(이 표를 채우는 도구는 소스 저장소에만 "
                  "있습니다).")
            return 1
        for qid, name, last_ym, catalog, why in found:
            if not last_ym:
                mark = f"모름 ({why})"
            else:
                mark = _ko(last_ym) + ("까지 확인" if at_anchor(qid) else "까지")
                # 값이 오는 것과 쓸 수 있는 것은 다르다. TS_01_08_001 은
                # 2025년까지 응답을 주지만 2023년부터 국가별이 빠지고
                # 합계 두 행만 온다 — "2025년까지 있다"만 보고 물으면
                # 표가 텅 빈 이유를 알 수 없다.
                if why:
                    mark += f" ({why})"
            print(f"{qid:32s} {mark:20s} {catalog:6s} {name}")
        return 0

    if args.mode == "latest":
        found = latest(args.qid)
        if found is None:
            print(f"{args.qid} 의 수록 시점을 모릅니다. 실제 호출로 "
                  f"확인하는 도구는 소스 저장소에만 있습니다. 기간을 "
                  f"넓혀 직접 조회해 보세요.")
            return 1
        if at_anchor(args.qid):
            print(f"{args.qid} 는 {_ko(found)} 까지 확인했습니다. "
                  f"그 뒤는 물어보지 않았으므로 더 있을 수 있습니다.")
        else:
            print(f"{args.qid} 는 {_ko(found)} 까지 나와 있습니다. "
                  f"그 뒤는 물어봤지만 값이 없었습니다.")
        return 0

    try:
        ym1, ym2 = resolve(args.spec, anchor=args.anchor)
    except PeriodError as exc:
        print(str(exc))
        return 2
    print(f"{args.spec} → {ym1} ~ {ym2} ({span(ym1, ym2)}개월)")
    return 0


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(_main())
