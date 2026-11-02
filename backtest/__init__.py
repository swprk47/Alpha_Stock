"""스윙 추천 규칙 백테스트(오프라인 도구). 앱 코드(backend/)는 읽기만 한다."""
import os
import sys

_BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
