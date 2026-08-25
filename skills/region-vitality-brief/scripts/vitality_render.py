"""지역 활력 브리프를 Artifact용 HTML로 렌더링한다.

문서 래퍼(<html>, <head>, <body>)는 넣지 않는다 — Artifact가 감싼다.
스타일과 출처 표기는 inbound-country-brief의 report.py에서 가져다 쓴다.

# 모듈 이름에 vitality_ 접두사를 붙인 이유: 다른 스킬도 render.py를
# 가지고 있다. 한 프로세스에서 둘 다 쓰면 먼저 import된 쪽이
# sys.modules를 차지해 다른 쪽 함수를 조용히 대신 실행한다.

**이 리포트의 한 문장은 맨 위에 온다.** "주민 한 명이 떠난 자리를
메우려면 관광객 몇 명이 와야 하는가" — 나머지는 그 숫자를 읽는 데
필요한 맥락이다. 표를 먼저 놓고 결론을 아래에 두면 아무도 안 읽는다.

**빠진 해를 지우지 않고 표시한다.** 데이터랩은 미발표를 0으로 말하고
이 스킬은 그 0을 걸러 낸다. 걸러 낸 자리를 빈칸으로 두면 사용자는
그래프가 짧아진 이유를 모른다.
"""
import html as html_mod
import pathlib
import sys

# <skills>/<이름>/scripts/x.py 에서 parents[2] 가 skills 루트다.
# 소스 트리든 배포본이든 사용자 설치 위치든 이 깊이는 같다.
_SKILLS_ROOT = pathlib.Path(__file__).resolve().parents[2]
for _p in (_SKILLS_ROOT / "inbound-country-brief" / "scripts",
           _SKILLS_ROOT / "datalab-fetch" / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from report import STYLE, footer_text  # noqa: E402

SUBSTITUTION_NOTE = (
    "이 숫자는 방문자 수가 아닙니다. 주민 한 명이 지역을 떠날 때 그 사람이 "
    "지역 안에서 쓰던 돈을 메우려면 관광객이 몇 명 와야 하는지입니다. "
    "실제로 그만큼 오고 있다는 뜻도, 와야 한다는 뜻도 아닙니다."
)
VISITOR_RATIO_NOTE = (
    "사이트가 이 값의 단위를 밝히지 않습니다. 절대 인원이 아니라 주민등록 "
    "인구를 1로 볼 때의 배수이므로, 연도 사이의 변화로만 읽으세요."
)
AMOUNT_NOTE = (
    "금액은 국민여행조사의 시도별 1회 평균 여행 지출액입니다. 이 시군구에서 "
    "실제로 쓴 돈이 아니라 소속 광역지자체의 평균값입니다."
)


def _esc(value):
    return html_mod.escape(str(value))


def _num(value, digits=0, suffix=""):
    if value is None:
        return "—"
    return f"{value:,.{digits}f}{suffix}"


def _people(value):
    if value is None:
        return "—"
    n = abs(value)
    if n >= 1_0000:
        return f"{value / 1_0000:,.1f}만명"
    return f"{value:,.0f}명"


def _money(value):
    if value is None:
        return "—"
    n = abs(value)
    if n >= 1_0000_0000:
        return f"{value / 1_0000_0000:,.1f}억원"
    if n >= 1_0000:
        return f"{value / 1_0000:,.0f}만원"
    return f"{value:,.0f}원"


def _headline(summ, meta):
    """리포트의 한 문장. 없으면 섹션 자체를 내지 않는다."""
    if not summ:
        return []
    where = _esc(summ["시군구명"] or meta["지역명"])
    tags = []
    if summ["인구감소지역"]:
        tags.append("인구감소지역")
    if summ["관심지역"]:
        tags.append("관심지역")
    tag_html = (f' <span class="note">({" · ".join(tags)})</span>'
                if tags else "")

    lodg, thdy = summ["대체필요_숙박"], summ["대체필요_당일"]
    parts = [f'<h2>주민 한 명이 떠나면{tag_html}</h2>',
             '<div class="card">',
             f'<p style="font-size:1.25rem;margin:.2rem 0">'
             f'<b>{where}</b> 주민 한 명의 지역 내 소비를 메우려면</p>',
             f'<p style="font-size:1.6rem;margin:.4rem 0">'
             f'숙박 관광객 <b>{_num(lodg)}명</b>'
             f' 또는 당일 관광객 <b>{_num(thdy)}명</b></p>',
             f'<p class="note">{summ["기준연도"]}년 기준 · 주민등록인구 '
             f'{_people(summ["주민등록인구"])} · 주민 1인당 지역 내 소비 '
             f'{_money(summ["주민1인당_역내소비액"])}</p>',
             '</div>']

    mix_l = summ["대체필요_숙박_구성비반영"]
    mix_t = summ["대체필요_당일_구성비반영"]
    if mix_l is not None and mix_t is not None:
        parts.append(
            f'<p>이 지역의 실제 방문 구성비(숙박 {_num(summ["숙박구성비"], 1)}% : '
            f'당일 {_num(summ["당일구성비"], 1)}%)를 반영하면 '
            f'<b>숙박 {_num(mix_l)}명 + 당일 {_num(mix_t)}명</b>입니다.</p>')

    parts.append(f'<div class="warn">{SUBSTITUTION_NOTE}</div>')
    parts.append(f'<p class="note">{AMOUNT_NOTE}</p>')

    inside = summ["역내소비비율"]
    if inside is not None:
        parts.append(
            f'<p>주민이 쓰는 돈 가운데 <b>{_num(inside, 1)}%</b>만 지역 '
            f'안에서 쓰입니다(나머지 {_num(summ["역외소비비율"], 1)}%는 역외). '
            f'역내 비율이 낮을수록 주민 한 명이 떠날 때 지역이 잃는 돈은 '
            f'적지만, 관광 소비도 새어 나가기 쉽습니다.</p>')
    return parts


def _vitals(health, meta):
    """체력 지표 여섯을 한 표에. 방향을 함께 적는다."""
    if not health:
        return []
    rows = []
    for item in health.values():
        points = item["값"]
        first, last = points[0], points[-1]
        unit = item["단위"]
        arrow = "—"
        if item["변화"] is not None:
            # 비율 지표의 차이는 %가 아니라 %p다. 28%에서 34.9%로 간 것을
            # "6.9% 늘었다"고 쓰면 24.6%p 늘었다는 뜻이 되어 버린다.
            delta_unit = "%p" if unit == "%" else unit
            arrow = f'{item["변화"]:+.1f}{delta_unit or ""}'
        direction = item["좋은방향"] or "—"
        missing = (f' <span class="note">({", ".join(item["빠진해"])} 결측)</span>'
                   if item["빠진해"] else "")
        rows.append(
            f'<tr><td>{_esc(item["라벨"])}{missing}</td>'
            f'<td>{_esc(first["연도"])}</td>'
            f'<td>{_num(first["값"], 1)}{_esc(unit)}</td>'
            f'<td>{_esc(last["연도"])}</td>'
            f'<td>{_num(last["값"], 1)}{_esc(unit)}</td>'
            f'<td>{_esc(arrow)}</td><td>{_esc(direction)}</td></tr>')

    parts = ['<h2>지역 체력</h2>',
             '<div class="scroll"><table><thead><tr>'
             '<th scope="col">지표</th><th scope="col">처음</th><th scope="col">값</th><th scope="col">끝</th><th scope="col">값</th>'
             '<th scope="col">변화</th><th scope="col">좋은 방향</th></tr></thead>'
             f'<tbody>{"".join(rows)}</tbody></table></div>',
             # 0을 걸러 낸 뒤라 물어본 기간의 양 끝이 아닐 수 있다.
             # 그것을 모르면 "5년간 -9.2%p"라고 쓰게 된다.
             '<p class="note">변화는 표의 "처음"과 "끝" 연도 사이의 '
             '값입니다. 결측인 해를 뺐다면 물어본 기간의 양 끝이 '
             '아닐 수 있으니 두 연도를 함께 읽으세요.</p>']
    if meta["빠진해"]:
        detail = " · ".join(f'{k} {", ".join(v)}'
                            for k, v in sorted(meta["빠진해"].items()))
        parts.append(
            f'<p class="note">값이 0으로 온 해는 표에서 뺐습니다: '
            f'{_esc(detail)}. 데이터랩은 결측을 0으로 보냅니다 — 그대로 '
            f'그리면 그 해에 값이 무너진 것처럼 보입니다. 재정자립도 '
            f'2024와 조출생률 2023은 <b>인구감소지역에서만</b> 0으로 '
            f'오는 것이 확인됐습니다(같은 해 강남구·춘천시에는 값이 '
            f'있습니다).</p>')
    parts.append(
        '<p class="note">재정자립도는 관광 성과가 아니라 지자체 재정 '
        '지표입니다. 조출생률(명/천명)과 인구밀도(명/㎢)는 사이트가 '
        '단위를 적지 않아 이 저장소가 산술로 확인한 것입니다 — '
        '인구밀도 x 면적이 주민등록인구와, 조출생률 x 인구 ÷ 1000이 '
        '출생아 수와 맞았습니다.</p>')
    return parts


def _jobs(jobs):
    """관광이 이 지역 고용을 얼마나 지탱하는가."""
    if not jobs:
        return []
    share = jobs["관광비중"]
    parts = [f'<h2>관광이 지탱하는 일자리 <span class="note">'
             f'({_esc(jobs["기준연도"])}년)</span></h2>']
    if not jobs.get("관광행찾음", True):
        # 제목만 뜬 빈 섹션을 내면 "관광 일자리가 없다"로 읽힌다.
        parts.append('<div class="warn">산업 목록에서 관광산업 행을 '
                     '찾지 못했습니다. 데이터랩이 분류를 바꿨을 수 '
                     '있으니 이 섹션의 수치를 인용하지 마세요.</div>')
    if share is not None:
        rank = next((i + 1 for i, x in enumerate(jobs["산업"]) if x["관광"]), None)
        rank_txt = (f'이 지역 {len(jobs["산업"])}개 산업 가운데 '
                    f'<b>{rank}위</b>' if rank else "")
        parts.append(
            f'<div class="card"><p style="font-size:1.2rem;margin:.2rem 0">'
            f'전체 종사자 {_people(jobs["전체종사자"])} 가운데 '
            f'<b>{_num(share, 1)}%</b>가 관광산업 '
            f'({_people(jobs["관광종사자"])} · 사업체 '
            f'{_num(jobs["관광사업체"])}개)</p>'
            f'<p class="note">{rank_txt}</p></div>')

    if jobs["관광업종"]:
        rows = "".join(
            f'<tr><td>{_esc(s["업종"])}</td><td>{_num(s["종사자"])}명</td>'
            f'<td>{_num(s["비중"], 1)}%</td></tr>'
            for s in jobs["관광업종"])
        parts.append(
            '<h3>관광산업 안의 구성</h3>'
            '<div class="scroll"><table><thead><tr><th scope="col">업종</th>'
            '<th scope="col">종사자</th><th scope="col">관광산업 내 비중</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>')

    top = [x for x in jobs["산업"] if not x["관광"]][:5]
    if top:
        rows = "".join(
            f'<tr><td>{_esc(x["산업"])}</td><td>{_num(x["종사자"])}명</td>'
            f'<td>{_num(x["비중"], 1)}%</td></tr>' for x in top)
        parts.append(
            '<h3>견줄 만한 다른 산업</h3>'
            '<div class="scroll"><table><thead><tr><th scope="col">산업</th>'
            '<th scope="col">종사자</th><th scope="col">전체 대비</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>'
            '<p class="note">관광산업은 표준산업분류를 가로질러 뽑아낸 '
            '분류이며, 위 산업들과 겹치지 않습니다(전체 합이 100%). '
            '나머지 산업은 관광 지표가 아닙니다.</p>')
    return parts


def _substitution_trend(trend):
    if not trend or not trend["값"]:
        return []
    rows = "".join(
        f'<tr><td>{_esc(p["연도"])}</td>'
        f'<td>{_money(p["주민1인당_역내소비액"])}</td>'
        f'<td>{_num(p["숙박"])}명</td><td>{_num(p["당일"])}명</td></tr>'
        for p in trend["값"])
    return ['<h2>대체 필요 관광객 수의 추이</h2>',
            '<div class="scroll"><table><thead><tr><th scope="col">연도</th>'
            '<th scope="col">주민 1인당 지역 내 소비</th><th scope="col">필요 숙박객</th>'
            '<th scope="col">필요 당일객</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>',
            '<p class="note">주민 1인당 소비가 늘면 대체에 필요한 관광객도 '
            '늘어납니다. 이 값이 커지는 것은 지역 경제가 나빠졌다는 뜻이 '
            '아니라, 주민 한 명의 무게가 무거워졌다는 뜻입니다.</p>']


def _visitor_ratio(ratio):
    if not ratio or not ratio["값"]:
        return []
    rows = "".join(
        f'<tr><td>{_esc(p["연도"])}</td><td>{_num(p["외지인"], 1)}</td>'
        f'<td>{_num(p["현지인"], 1)}</td></tr>' for p in ratio["값"])
    return ['<h2>주민등록 인구 대비 방문</h2>',
            '<div class="scroll"><table><thead><tr><th scope="col">연도</th>'
            '<th scope="col">외지인</th><th scope="col">현지인</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>',
            f'<div class="warn">{VISITOR_RATIO_NOTE}</div>']


def _ages(ages):
    if not ages:
        return []
    bands = ages["구간"]
    peak = max((b for b in bands if b["인구"] is not None),
               key=lambda b: b["인구"], default=None)
    rows = "".join(
        f'<tr><td>{_esc(b["구간"])}</td><td>{_num(b["인구"])}명</td>'
        f'<td>{_num(b["비중"], 1)}%</td></tr>' for b in bands)
    parts = [f'<h2>연령 분포 <span class="note">'
             f'({_esc(ages["기준연도"])}년 · 총 {_people(ages["총인구"])})</span></h2>',
             '<div class="scroll"><table><thead><tr><th scope="col">연령</th>'
             '<th scope="col">인구</th><th scope="col">비중</th></tr></thead>'
             f'<tbody>{rows}</tbody></table></div>']
    if peak:
        parts.append(f'<p>가장 두꺼운 층은 <b>{_esc(peak["구간"])}</b>'
                     f'({_num(peak["비중"], 1)}%)입니다.</p>')
    return parts


def _coverage(meta):
    parts = ['<h2>데이터 수록 현황</h2>',
             f'<p>지표 {meta["수록지표"]}/{meta["전체지표"]}개를 받았습니다.</p>']
    if meta["미수록"]:
        rows = "".join(f'<tr><td>{_esc(k)}</td><td>{_esc(v)}</td></tr>'
                       for k, v in sorted(meta["미수록"].items()))
        parts.append('<div class="scroll"><table><thead><tr><th scope="col">지표</th>'
                     '<th scope="col">받지 못한 이유</th></tr></thead>'
                     f'<tbody>{rows}</tbody></table></div>')
    parts.append(
        '<p class="note">빈 응답은 오류가 아니라 "아직 발표되지 않았다"인 '
        '경우가 많습니다. 그 지역에 값이 0이라는 뜻이 아닙니다.</p>')
    return parts


def render(data, meta):
    parts = [STYLE, '<div class="wrap">']
    parts.append(f'<h1>{_esc(meta["지역명"])} 지역 활력 브리프</h1>')
    parts.append(f'<p class="sub">기준 기간 {_esc(meta["기준기간"])} · '
                 f'지역코드 {_esc(meta["지역코드"])}</p>')

    if meta["세션상태"] == "만료":
        parts.append('<div class="warn">로그인 세션이 만료되어 일부 지표를 '
                     '가져오지 못했습니다.</div>')
    for warning in meta["검산경고"]:
        parts.append(f'<div class="warn">{_esc(warning)}</div>')

    parts += _headline(data.get("요약"), meta)
    parts += _jobs(data.get("관광고용"))
    parts += _vitals(data.get("체력"), meta)
    parts += _substitution_trend(data.get("대체추이"))
    parts += _visitor_ratio(data.get("인구대비방문"))
    parts += _ages(data.get("연령분포"))
    parts += _coverage(meta)

    parts.append(f'<footer>{_esc(footer_text())}</footer>')
    parts.append("</div>")
    return "\n".join(parts)
