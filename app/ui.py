"""Static HTML for the browser UI."""

HTML_INDEX = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RAG · Телефонный справочник</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         margin: 0; background: #f4f5f7; color: #1a1a1a; }
  header { background: #1f2937; color: #fff; padding: 12px 20px;
           display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
  header h1 { margin: 0; font-size: 18px; font-weight: 600; }
  header .status { font-size: 12px; opacity: 0.85; }
  header .status .dot { display: inline-block; width: 8px; height: 8px;
                        border-radius: 50%; background: #ef4444; margin-right: 4px; }
  header .status.ok .dot { background: #22c55e; }
  main { max-width: 1200px; margin: 0 auto; padding: 20px; }
  .chat { background: #fff; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.08);
          display: flex; flex-direction: column; height: calc(100vh - 160px); }
  .messages { flex: 1; overflow-y: auto; padding: 16px; }
  .msg { margin-bottom: 12px; padding: 10px 14px; border-radius: 10px;
         max-width: 90%; white-space: pre-wrap; word-wrap: break-word; }
  .msg.user { background: #dbeafe; margin-left: auto; }
  .msg.assistant { background: #f3f4f6; }
  .msg.assistant table { border-collapse: collapse; margin-top: 8px; font-size: 13px; }
  .msg.assistant th, .msg.assistant td { border: 1px solid #d1d5db; padding: 4px 8px; text-align: left; }
  .msg.assistant th { background: #e5e7eb; }
  .msg.assistant em { color: #6b7280; }
  .input-row { display: flex; gap: 8px; padding: 12px; border-top: 1px solid #e5e7eb; }
  .input-row textarea { flex: 1; resize: none; border: 1px solid #d1d5db;
                        border-radius: 8px; padding: 8px 12px; font-size: 14px;
                        font-family: inherit; min-height: 44px; max-height: 120px; }
  .input-row button { background: #2563eb; color: #fff; border: 0; border-radius: 8px;
                      padding: 0 20px; font-size: 14px; cursor: pointer; font-weight: 500; }
  .input-row button:disabled { background: #93c5fd; cursor: not-allowed; }
  .tools { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
  .tools button { background: #fff; border: 1px solid #d1d5db; border-radius: 8px;
                  padding: 6px 12px; font-size: 13px; cursor: pointer; }
  .tools button:hover { background: #f9fafb; }
  .hint { font-size: 12px; color: #6b7280; margin-top: 6px; }
  .sources { font-size: 11px; color: #6b7280; margin-top: 6px; }
</style>
</head>
<body>
<header>
  <h1>📞 RAG · Телефонный справочник</h1>
  <div class="status" id="status"><span class="dot"></span>проверка...</div>
</header>
<main>
  <div class="chat">
    <div class="messages" id="messages">
      <div class="msg assistant">
        👋 <b>Привет! Я — справочная система.</b><br><br>
        <b>Что можно спросить:</b><br>
        • <b>Телефон по фамилии:</b> «тел Жданко», «телефон Мельникова»<br>
        • <b>Телефон по отделу:</b> «тел ИТ», «тел АУО», «тел МТО»<br>
        • <b>Список сотрудников:</b> «Кто работает в ИТ отделе», «Сколько людей в бухгалтерии»<br>
        • <b>Отдел сотрудника:</b> «в каком отделе Дуванский»<br>
        • <b>Список отделов:</b> «Какие отделы есть?»<br>
        • <b>Токены/ключи:</b> «Какой токен HF?»<br><br>
        <i>Начните с вопроса «Какие отделы есть?», чтобы увидеть все отделы.</i>
      </div>
    </div>
    <div class="input-row">
      <textarea id="input" placeholder="Например: тел Жданко, тел ИТ, какие отделы есть?" rows="1"></textarea>
      <button id="send">Отправить</button>
    </div>
  </div>
  <div class="tools">
    <button onclick="doHealth()">🏥 Здоровье</button>
    <button onclick="doScan()">🔄 Сканировать</button>
    <button onclick="doReindex()">📥 Переиндексировать XLSX</button>
    <span class="hint" id="hint"></span>
  </div>
</main>
<script>
(function () {
  var messagesEl = document.getElementById('messages');
  var inputEl = document.getElementById('input');
  var sendEl = document.getElementById('send');
  var statusEl = document.getElementById('status');
  var hintEl = document.getElementById('hint');

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // Markdown-таблица | a | b | ... → HTML-таблица
  function renderMarkdown(text) {
    var lines = String(text == null ? '' : text).split(String.fromCharCode(10));
    var out = [];
    var inTable = false;
    var inList = false;
    var i = 0;
    while (i < lines.length) {
      var line = lines[i];
      var trimmed = line.trim();

      // Таблицы
      if (trimmed.charAt(0) === '|' && trimmed.charAt(trimmed.length - 1) === '|') {
        if (inList) { out.push('</ul>'); inList = false; }
        var next = (i + 1 < lines.length) ? lines[i + 1] : '';
        if (!inTable && next.indexOf('---') !== -1) {
          inTable = true;
          out.push('<table><thead><tr>');
          var cells0 = trimmed.split('|').slice(1, -1);
          for (var k = 0; k < cells0.length; k++) {
            out.push('<th>' + esc(cells0[k].trim()) + '</th>');
          }
          out.push('</tr></thead><tbody>');
          i += 2;
          continue;
        } else if (inTable) {
          var cells = trimmed.split('|').slice(1, -1);
          out.push('<tr>');
          for (var j = 0; j < cells.length; j++) {
            out.push('<td>' + esc(cells[j].trim()) + '</td>');
          }
          out.push('</tr>');
          i += 1;
          continue;
        }
      } else if (inTable) {
        out.push('</tbody></table>');
        inTable = false;
      }

      // Маркированные списки: "- пункт" или "• пункт"
      var isListItem = (trimmed.indexOf('- ') === 0) || (trimmed.indexOf('• ') === 0) || (trimmed.indexOf('* ') === 0);
      if (isListItem) {
        if (!inList) {
          out.push('<ul>');
          inList = true;
        }
        var itemText = trimmed.replace(/^[-•*]\s+/, '');
        out.push('<li>' + esc(itemText) + '</li>');
        i += 1;
        continue;
      } else if (inList) {
        out.push('</ul>');
        inList = false;
      }

      // Обычный текст
      if (trimmed === '') {
        out.push('<br>');
      } else if (trimmed.charAt(0) === '_' && trimmed.charAt(trimmed.length - 1) === '_') {
        out.push('<em>' + esc(trimmed.slice(1, -1)) + '</em>');
      } else {
        out.push(esc(line));
      }
      i += 1;
    }
    if (inTable) out.push('</tbody></table>');
    if (inList) out.push('</ul>');
    return out.join('');
  }

  function addMessage(role, text, sources) {
    var div = document.createElement('div');
    div.className = 'msg ' + role;
    if (role === 'assistant') {
      div.innerHTML = renderMarkdown(text);
      if (sources && sources.length) {
        var sEl = document.createElement('div');
        sEl.className = 'sources';
        sEl.textContent = 'Источники: ' + sources.join(', ');
        div.appendChild(sEl);
      }
    } else {
      div.textContent = text;
    }
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function send() {
    var q = inputEl.value.trim();
    if (!q) return;
    addMessage('user', q);
    inputEl.value = '';
    sendEl.disabled = true;
    hintEl.textContent = 'думаю...';
    var t0 = (window.performance && performance.now) ? performance.now() : Date.now();
    fetch('/v1/chat/completions', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({model: 'rag', messages: [{role: 'user', content: q}]})
    }).then(function (r) { return r.json(); }).then(function (d) {
      var ans = (d.choices && d.choices[0] && d.choices[0].message && d.choices[0].message.content) || '(пусто)';
      addMessage('assistant', ans, d.x_rag_sources || []);
      var t1 = (window.performance && performance.now) ? performance.now() : Date.now();
      hintEl.textContent = ((t1 - t0) / 1000).toFixed(2) + ' с';
    }).catch(function (e) {
      addMessage('assistant', 'Ошибка: ' + e.message);
      hintEl.textContent = '';
    }).then(function () {
      sendEl.disabled = false;
    });
  }

  function doHealth() {
    hintEl.textContent = 'health...';
    fetch('/health').then(function (r) { return r.json(); }).then(function (d) {
      addMessage('assistant', 'health:\n' + JSON.stringify(d, null, 2));
      hintEl.textContent = '';
    }).catch(function () { hintEl.textContent = 'ошибка'; });
  }

  function doScan() {
    hintEl.textContent = 'scan...';
    fetch('/scan', {method: 'POST'}).then(function (r) { return r.json(); }).then(function (d) {
      addMessage('assistant', 'scan:\n' + JSON.stringify(d, null, 2));
      hintEl.textContent = '';
    }).catch(function () { hintEl.textContent = 'ошибка'; });
  }

  function doReindex() {
    var name = prompt('Имя файла (source):', 'Телефонный справочник.xlsx');
    if (!name) return;
    hintEl.textContent = 'reindex...';
    fetch('/reindex/' + encodeURIComponent(name), {method: 'POST'})
      .then(function (r) { return r.json(); })
      .then(function (d) {
        addMessage('assistant', 'reindex:\n' + JSON.stringify(d, null, 2));
        hintEl.textContent = '';
      }).catch(function () { hintEl.textContent = 'ошибка'; });
  }

  function checkStatus() {
    fetch('/health', {cache: 'no-store'}).then(function (r) { return r.json(); }).then(function (d) {
      if (d.status === 'ok' && d.model_loaded && d.llm_ready) {
        statusEl.textContent = `онлайн · модель загружена (${d.llm_mode}: ${d.llm_model})`;
        statusEl.style.color = '#2e7d32';
      } else if (d.status === 'ok' && d.model_loaded && !d.llm_ready) {
        statusEl.textContent = `онлайн · embeddings OK, LLM недоступна (${d.llm_mode})`;
        statusEl.style.color = '#f57c00';
      } else if (d.status === 'ok' && d.model_loaded) {
        statusEl.className = 'status ok';
        statusEl.innerHTML = '<span class="dot"></span>онлайн · модель загружена';
      } else {
        statusEl.className = 'status';
        statusEl.innerHTML = '<span class="dot"></span>деградация';
      }
    }).catch(function (e) {
      statusEl.className = 'status';
      statusEl.innerHTML = '<span class="dot"></span>offline';
    });
  }

  sendEl.addEventListener('click', send);
  inputEl.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  });
  window.doHealth = doHealth;
  window.doScan = doScan;
  window.doReindex = doReindex;

  checkStatus();
  setInterval(checkStatus, 10000);
})();
</script>
</body>
</html>"""

__all__ = ["HTML_INDEX"]
