# Claude Code 첫 프롬프트 (복사해서 붙여넣기)

리포 루트에 `CLAUDE.md`와 `PROGRESS.md`를 넣은 뒤, 브랜치를 맞추고 시작하세요.

```bash
git checkout feat/auth-and-order-validation && git pull
```

---

Alpha_Stock 작업을 이어서 하려고 해. 이전 대화(다른 AI)에서 진행하던 프로젝트야.

먼저 아래 순서로 읽어줘.
1. `CLAUDE.md` (작업 원칙·핵심 설계)
2. `PROGRESS.md` (결정사항·완료/남은 작업)
3. 현재 상태 검증: `git log --oneline | head`, `pytest -q`, 프론트 문법검사

읽고 나서 **코드는 쓰지 말고**, 아래만 답해줘.
- 현재 브랜치/커밋과 pytest 결과 (PROGRESS.md의 "2b까지 완료, 56 passed"와 일치하는지)
- 3단계(A2)를 하려면 어떤 파일의 어떤 함수를 고칠지 계획 (`get_recommendations`, 프론트의 추천 카드 렌더링, `is_fractional` 처리)
- PROGRESS.md와 실제 코드가 다른 점이 있으면 알려줘

내가 "진행해"라고 하면 그때 3단계만 작성해줘. 한 단계가 끝나면 pytest와 프론트 문법검사 결과를 보고하고, 내가 push 완료를 알리면 다음 단계를 시작해도 되는지 먼저 물어봐줘. main 직접 수정은 금지야.
