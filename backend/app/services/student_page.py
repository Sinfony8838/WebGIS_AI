"""Self-contained mobile page for students joining a class session.

Served at ``GET /student/{join_code}`` with no auth token: the join code
itself is the credential.  Keeps zero build-time dependencies — plain
HTML + inline JS polling the two ``/api/student/*`` endpoints.
"""

from __future__ import annotations


STUDENT_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1" />
<title>课堂作答 · WebGIS-AI</title>
<style>
  :root {{ color-scheme: light; }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: "Microsoft YaHei UI", "PingFang SC", "Segoe UI", sans-serif;
    background: linear-gradient(180deg, #eef4fb 0%, #dce8f5 100%);
    min-height: 100vh; padding: 20px 16px 40px;
    color: #16324a;
  }}
  .card {{
    background: rgba(255, 255, 255, 0.92); border-radius: 16px;
    box-shadow: 0 8px 28px rgba(22, 50, 74, 0.12);
    padding: 20px 18px; max-width: 460px; margin: 0 auto 14px;
  }}
  h1 {{ font-size: 18px; margin-bottom: 4px; }}
  .sub {{ font-size: 12px; color: #56748f; margin-bottom: 14px; }}
  label {{ font-size: 13px; color: #375a78; display: block; margin-bottom: 6px; }}
  input[type="text"] {{
    width: 100%; padding: 12px 14px; font-size: 16px;
    border: 1px solid #b9cee0; border-radius: 10px; outline: none;
  }}
  input[type="text"]:focus {{ border-color: #2f81f7; }}
  button {{
    width: 100%; margin-top: 12px; padding: 13px; font-size: 16px; font-weight: 600;
    color: #fff; background: #2f81f7; border: 0; border-radius: 10px;
  }}
  button:disabled {{ background: #9db8d4; }}
  .option {{
    display: block; width: 100%; text-align: left; margin-top: 10px;
    padding: 13px 14px; font-size: 15px; font-weight: 500;
    background: #f2f7fc; color: #16324a; border: 1.5px solid #c9dbeb; border-radius: 12px;
  }}
  .option.selected {{ border-color: #2f81f7; background: #e3efff; color: #114a8f; }}
  textarea {{
    width: 100%; margin-top: 10px; padding: 12px 14px; min-height: 96px;
    font-size: 15px; font-family: inherit;
    border: 1px solid #b9cee0; border-radius: 10px; outline: none; resize: vertical;
  }}
  .state {{ text-align: center; padding: 26px 8px; font-size: 15px; color: #56748f; }}
  .state strong {{ display: block; font-size: 17px; color: #16324a; margin-bottom: 6px; }}
  .badge {{
    display: inline-block; font-size: 12px; padding: 3px 10px; border-radius: 999px;
    background: #e3efff; color: #114a8f; margin-bottom: 10px;
  }}
  .question-text {{ font-size: 16px; font-weight: 600; line-height: 1.55; margin-bottom: 4px; }}
  .done {{ color: #15803d; }}
</style>
</head>
<body>
  <div class="card" id="join-card">
    <h1>加入课堂</h1>
    <p class="sub">课堂码：{join_code}</p>
    <label for="nickname">你的姓名或昵称</label>
    <input type="text" id="nickname" maxlength="16" placeholder="例如：李明" />
    <button id="join-btn">进入课堂</button>
  </div>

  <div class="card" id="main-card" style="display:none">
    <span class="badge" id="stage-badge">课堂进行中</span>
    <div id="content"><div class="state">等待老师发起提问…</div></div>
  </div>

<script>
(function () {{
  var JOIN_CODE = "{join_code}";
  var API = "/api/student/" + JOIN_CODE;
  var nickname = localStorage.getItem("webgis-ai-student-nickname") || "";
  var currentQuestionId = "";
  var selectedIndex = -1;
  var answeredQuestionId = localStorage.getItem("webgis-ai-answered-" + JOIN_CODE) || "";

  var joinCard = document.getElementById("join-card");
  var mainCard = document.getElementById("main-card");
  var content = document.getElementById("content");
  var stageBadge = document.getElementById("stage-badge");
  var nicknameInput = document.getElementById("nickname");
  nicknameInput.value = nickname;

  document.getElementById("join-btn").addEventListener("click", function () {{
    var value = nicknameInput.value.trim();
    if (!value) {{ nicknameInput.focus(); return; }}
    nickname = value;
    localStorage.setItem("webgis-ai-student-nickname", nickname);
    joinCard.style.display = "none";
    mainCard.style.display = "block";
    poll();
  }});

  function renderWaiting(message) {{
    currentQuestionId = "";
    content.innerHTML = '<div class="state"><strong>' + (message || "等待老师发起提问…") + "</strong>请保持页面打开</div>";
  }}

  function renderSubmitted() {{
    content.innerHTML = '<div class="state done"><strong>✓ 已提交</strong>等待老师公布结果</div>';
  }}

  function renderQuestion(question) {{
    currentQuestionId = question.question_id;
    selectedIndex = -1;
    var html = '<p class="question-text">' + escapeHtml(question.text) + "</p>";
    if (question.type === "choice") {{
      for (var i = 0; i < question.options.length; i++) {{
        html += '<button type="button" class="option" data-index="' + i + '">' +
          String.fromCharCode(65 + i) + ". " + escapeHtml(question.options[i]) + "</button>";
      }}
      html += '<button id="submit-btn" disabled>提交答案</button>';
    }} else {{
      html += '<textarea id="open-answer" maxlength="120" placeholder="写下你的回答（简短即可）"></textarea>';
      html += '<button id="submit-btn">提交答案</button>';
    }}
    content.innerHTML = html;

    var optionButtons = content.querySelectorAll(".option");
    for (var j = 0; j < optionButtons.length; j++) {{
      optionButtons[j].addEventListener("click", function () {{
        selectedIndex = parseInt(this.getAttribute("data-index"), 10);
        var all = content.querySelectorAll(".option");
        for (var k = 0; k < all.length; k++) {{ all[k].classList.remove("selected"); }}
        this.classList.add("selected");
        document.getElementById("submit-btn").disabled = false;
      }});
    }}
    document.getElementById("submit-btn").addEventListener("click", submit);
  }}

  function submit() {{
    var payload = {{ nickname: nickname, question_id: currentQuestionId }};
    if (selectedIndex >= 0) {{ payload.choice_index = selectedIndex; }}
    var openAnswer = document.getElementById("open-answer");
    if (openAnswer) {{
      var text = openAnswer.value.trim();
      if (!text) {{ openAnswer.focus(); return; }}
      payload.text = text;
    }}
    var btn = document.getElementById("submit-btn");
    btn.disabled = true;
    btn.textContent = "提交中…";
    fetch(API + "/answers", {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify(payload)
    }}).then(function (response) {{
      if (!response.ok) {{ throw new Error("submit failed"); }}
      answeredQuestionId = currentQuestionId;
      localStorage.setItem("webgis-ai-answered-" + JOIN_CODE, answeredQuestionId);
      renderSubmitted();
    }}).catch(function () {{
      btn.disabled = false;
      btn.textContent = "提交答案（重试）";
    }});
  }}

  function poll() {{
    fetch(API + "/state?nickname=" + encodeURIComponent(nickname))
      .then(function (response) {{
        if (response.status === 404) {{ renderWaiting("课堂已结束"); return null; }}
        return response.json();
      }})
      .then(function (payload) {{
        if (!payload) {{ return; }}
        if (payload.stage_title) {{ stageBadge.textContent = "当前环节：" + payload.stage_title; }}
        var question = payload.active_question;
        if (!question || !question.question_id) {{
          renderWaiting();
        }} else if (question.question_id === answeredQuestionId) {{
          if (currentQuestionId !== question.question_id) {{
            currentQuestionId = question.question_id;
            renderSubmitted();
          }}
        }} else if (question.question_id !== currentQuestionId) {{
          renderQuestion(question);
        }}
      }})
      .catch(function () {{ /* keep polling */ }})
      .finally(function () {{ setTimeout(poll, 2000); }});
  }}

  function escapeHtml(value) {{
    return String(value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }}

  if (nickname) {{
    joinCard.style.display = "none";
    mainCard.style.display = "block";
    poll();
  }}
}})();
</script>
</body>
</html>
"""


def render_student_page(join_code: str) -> str:
    safe_code = "".join(ch for ch in str(join_code) if ch.isalnum())[:12]
    return STUDENT_PAGE_TEMPLATE.format(join_code=safe_code)
