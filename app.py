from flask import Flask, request, jsonify, render_template
from anthropic import Anthropic
from dotenv import load_dotenv
import json, re, os

load_dotenv()

app = Flask(__name__)
client = Anthropic()

BASE_STYLE = """
너는 네이버 블로거야. 아래 공통 스타일을 따라서 블로그 포스팅을 작성해:

[공통 말투]
- 항상 "안녕하세요~" 로 시작
- 친근한 존댓말 (~했어요, ~이에요, ~네요)
- "~~", "^^", "ㅎㅎ", "ㅠㅠ" 자연스럽게 사용
- 짧은 문장 위주, 문장 사이 줄바꿈 많이
- 감탄은 "!!!", "~~~" 여러 개 붙이기
- 개인 경험 ("저는~", "저희는~") 자연스럽게 녹이기
- 마지막은 추천 멘트로 마무리
"""

TYPE_STYLE = {
    'restaurant': """
[타입: 맛집 리뷰]
- 가격 강조할 때 "개이득!" "완전 가성비!" 같은 표현
- "집에서 ~분 거리" 등 이동 경험 포함
- 음식 맛 표현: "맛도 일품!", "군침 돌아요", "싱싱해요", "완전 맛있어요~~"
[글 구조] 인사+요약 → 가게정보(주소/시간/편의시설) → 방문경험(이동/동행) → 메뉴+가격+가성비 → 음식묘사 → 분위기 → 별점총평 → 추천멘트
""",
    'item': """
[타입: 아이템/제품 리뷰]
- 구매 계기와 첫인상을 생생하게
- "이건 진짜 좋아요", "생각보다..." 등 솔직한 표현
- 장단점을 균형 있게
[글 구조] 인사+제품소개+구매계기 → 제품정보(브랜드/구매처/가격) → 언박싱&첫인상 → 실사용후기(장점) → 아쉬운점 → 별점총평(품질/가성비/디자인/편의성) → 구매추천멘트
""",
    'travel': """
[타입: 여행기]
- 여행 설렘과 감동을 생생하게
- "대박이에요!", "완전 추천!", "다시 가고 싶어요~" 표현
- 교통/입장료/예약 팁 등 실용 정보 포함
[글 구조] 인사+여행지소개+요약 → 여행정보(기간/교통/숙소) → 일정&주요방문지 → 맛집/카페소개 → 여행팁&주의사항 → 총비용 → 별점총평(경치/음식/숙소/접근성) → 추천멘트
""",
    'review': """
[타입: 일반 후기 (공연/전시/영화/도서/강의 등)]
- 경험을 솔직하고 생생하게
- 감정과 느낀점을 풍부하게
- 추천/비추천 이유 명확하게
[글 구조] 인사+대상소개+방문계기 → 기본정보(장소/날짜/비용) → 주요내용&경험 → 인상깊은점 → 아쉬웠던점 → 별점총평(만족도/추천도/완성도/가성비) → 총평멘트
""",
}

LENGTH_MAP = {
    'short':  ('짧게 (500자 내외)', 1500),
    'medium': ('보통 (1500자 내외)', 3500),
    'long':   ('길게 (2000자 이상)', 5000),
}

TONE_MAP = {
    'friendly':  '[톤] 친근한 스타일 — "^^", "ㅎㅎ", "~~", "!!!" 활용, 활기차고 공감 가는 표현',
    'emotional': '[톤] 감성적인 스타일 — 분위기·감정·계절감을 서정적으로, 잔잔하고 여운 있는 마무리',
    'pro':       '[톤] 전문 리뷰어 스타일 — 객관적 분석, 체계적 장단점 비교, 격식 있는 존댓말',
    'funny':     '[톤] 유머러스한 스타일 — 재미있는 비유·과장·반전, 밈 표현, 읽으면서 웃음 나오는 텍스트',
}

HASHTAG_GUIDE = {
    'restaurant': '지역명+음식종류+가게명 조합으로 10~15개',
    'item':       '제품명+브랜드+카테고리+사용후기 조합으로 10~15개',
    'travel':     '여행지+지역명+여행종류 조합으로 10~15개',
    'review':     '대상명+카테고리+감상 조합으로 10~15개',
}


def build_info(data, blog_type):
    category = data.get('category', '')
    extra    = data.get('extra', '')
    stars    = data.get('stars', {})

    def s(key):
        v = int(stars.get(key, 0))
        return '⭐' * v if v else '미입력'

    if blog_type == 'restaurant':
        facilities = []
        if data.get('parking'):     facilities.append('주차 가능')
        if data.get('waiting'):     facilities.append('웨이팅 있음')
        if data.get('reservation'): facilities.append('예약 가능')
        star_vals = [stars.get(k, 0) for k in ('taste','service','price','mood')]
        star_text = (f"맛 {s('taste')} / 서비스 {s('service')} / 가격 {s('price')} / 분위기 {s('mood')}"
                     if any(star_vals) else '별점 없음')
        return f"""카테고리: {category}
가게명: {data.get('restaurant','')}
주소: {data.get('address','')}
영업시간: {data.get('hours','')}
편의시설: {', '.join(facilities) if facilities else '정보 없음'}
주문 메뉴: {data.get('menus','')}
가격: {data.get('price','')}
동행: {data.get('companion','')}
거리/이동: {data.get('distance','')}
분위기: {data.get('atmosphere','')}
추가 메모: {extra}
별점: {star_text}"""

    elif blog_type == 'item':
        star_vals = [stars.get(k, 0) for k in ('quality','costperf','design','usability')]
        star_text = (f"품질 {s('quality')} / 가성비 {s('costperf')} / 디자인 {s('design')} / 편의성 {s('usability')}"
                     if any(star_vals) else '별점 없음')
        return f"""카테고리: {category}
제품명: {data.get('item_name','')}
브랜드: {data.get('brand','')}
구매처: {data.get('purchase','')}
가격: {data.get('item_price','')}
사용 기간: {data.get('use_period','')}
장점: {data.get('pros','')}
단점: {data.get('cons','')}
추가 메모: {extra}
별점: {star_text}"""

    elif blog_type == 'travel':
        star_vals = [stars.get(k, 0) for k in ('scenery','tfood','tlodging','access')]
        star_text = (f"경치 {s('scenery')} / 음식 {s('tfood')} / 숙소 {s('tlodging')} / 접근성 {s('access')}"
                     if any(star_vals) else '별점 없음')
        return f"""카테고리: {category}
여행지: {data.get('destination','')}
여행 기간: {data.get('period','')}
교통편: {data.get('transport','')}
숙소: {data.get('lodging','')}
동행: {data.get('companion','')}
주요 방문지/일정: {data.get('spots','')}
총 비용: {data.get('total_cost','')}
추가 메모: {extra}
별점: {star_text}"""

    elif blog_type == 'review':
        star_vals = [stars.get(k, 0) for k in ('satisfaction','recommend','complete','worth')]
        star_text = (f"만족도 {s('satisfaction')} / 추천도 {s('recommend')} / 완성도 {s('complete')} / 가성비 {s('worth')}"
                     if any(star_vals) else '별점 없음')
        return f"""카테고리: {category}
대상/제목: {data.get('subject','')}
장소/플랫폼: {data.get('venue','')}
날짜: {data.get('review_date','')}
비용: {data.get('review_cost','')}
주요 내용: {data.get('review_content','')}
인상깊은 점: {data.get('impression','')}
추가 메모: {extra}
별점: {star_text}"""

    return ''


def sanitize_json(raw):
    """JSON 문자열 값 내부의 리터럴 개행/탭을 이스케이프 처리."""
    result = []
    in_string = False
    escaped = False
    for ch in raw:
        if escaped:
            result.append(ch)
            escaped = False
        elif ch == '\\' and in_string:
            result.append(ch)
            escaped = True
        elif ch == '"':
            in_string = not in_string
            result.append(ch)
        elif in_string and ch == '\n':
            result.append('\\n')
        elif in_string and ch == '\r':
            result.append('\\r')
        elif in_string and ch == '\t':
            result.append('\\t')
        else:
            result.append(ch)
    return ''.join(result)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/generate', methods=['POST'])
def generate():
    try:
        data        = request.json
        blog_type   = data.get('blog_type', 'restaurant')
        length      = data.get('length', 'medium')
        tone        = data.get('tone', 'friendly')
        photo_count = data.get('photo_count', 5)

        length_label, max_tokens = LENGTH_MAP.get(length, LENGTH_MAP['medium'])
        system_prompt = (BASE_STYLE
                         + TYPE_STYLE.get(blog_type, TYPE_STYLE['restaurant'])
                         + '\n' + TONE_MAP.get(tone, TONE_MAP['friendly']))

        info_text   = build_info(data, blog_type)
        hashtag_tip = HASHTAG_GUIDE.get(blog_type, '')

        user_prompt = f"""아래 정보로 블로그 포스팅을 작성하고, 결과를 반드시 아래 JSON 형식으로만 응답해줘.
다른 텍스트 없이 JSON만 출력해.

[정보]
{info_text}
글 길이: {length_label}
사진 자리 개수: {photo_count}개 (본문에 [사진1], [사진2] 형태로 삽입)

[JSON 형식]
{{
  "content": "블로그 본문 (줄바꿈 많이, 사진 자리 [사진1][사진2]... 포함, 별점 항목 포함)",
  "titles": ["제목1", "제목2", "제목3"],
  "hashtags": "#태그1 #태그2 ...",
  "instagram": "인스타그램용 짧은 캡션 (이모지 많이, 3~5줄, 해시태그 포함)",
  "thumbnail": "썸네일용 짧은 문구 (10자 이내, 임팩트 있게)"
}}

titles: 클릭률 높고 개성 있는 네이버 블로그 스타일 제목 3개.
hashtags: {hashtag_tip}.
instagram: 인스타 감성으로 짧고 임팩트 있게.
thumbnail: 블로그 대표 썸네일에 들어갈 짧은 핵심 문구.
"""

        message = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{'role': 'user', 'content': user_prompt}]
        )

        raw = message.content[0].text.strip()
        if raw.startswith('```'):
            raw = raw.split('\n', 1)[1]
            raw = raw.rsplit('```', 1)[0].strip()

        raw = sanitize_json(raw)

        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r'\{[\s\S]*\}', raw)
            if match:
                try:
                    result = json.loads(match.group())
                except json.JSONDecodeError:
                    return jsonify({'error': '응답 파싱 실패', 'raw': raw[:500]}), 500
            else:
                return jsonify({'error': '응답 파싱 실패', 'raw': raw[:500]}), 500

        if 'titles' in result and not isinstance(result['titles'], list):
            result['titles'] = [s.strip() for s in re.split(r'\n|\d+\.', str(result['titles'])) if s.strip()]

        return jsonify(result)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
