const TOKEN_PROPERTY = 'FOLLOWUP_MAIL_TOKEN';
const APP_VERSION = '2026-07-01-html-mail-v1';

function doGet(e) {
  try {
    const params = getParams_(e);
    const action = String(params.action || 'status');
    const expectedToken = PropertiesService.getScriptProperties().getProperty(TOKEN_PROPERTY);

    if (expectedToken && action !== 'status' && params.token !== expectedToken) {
      return jsonResponse_({ ok: false, error: 'invalid token' });
    }

    if (action === 'sendTest') {
      const to = String(params.to || '').trim();
      if (!to) return jsonResponse_({ ok: false, error: 'missing to' });
      MailApp.sendEmail({
        to,
        subject: 'GAS mail send test',
        body: 'This is a GAS mail send test. No dashboard data is included.',
        attachments: [Utilities.newBlob('test,result\nmail,ok\n', 'text/csv', 'gas_mail_test.csv')],
      });
      return jsonResponse_({ ok: true, action, sentTo: to });
    }

    if (action === 'sendDashboard') {
      const to = String(params.to || '').trim();
      const dashboardUrl = String(params.dashboardUrl || '').trim();
      if (!to || !dashboardUrl) return jsonResponse_({ ok: false, error: 'missing to or dashboardUrl' });
      const result = sendDashboardFollowup_(to, dashboardUrl);
      return jsonResponse_({ ok: true, action, sentTo: to, month: result.month, count: result.count });
    }

    return jsonResponse_({
      ok: true,
      app: 'followup_mailer',
      version: APP_VERSION,
      actions: ['status', 'sendTest', 'sendDashboard'],
      message: 'GAS endpoint is reachable',
      mailQuota: MailApp.getRemainingDailyQuota(),
      time: new Date().toISOString(),
    });
  } catch (error) {
    return jsonResponse_({ ok: false, error: String(error) });
  }
}

function authorizeMailApp() {
  const quota = MailApp.getRemainingDailyQuota();
  const response = UrlFetchApp.fetch('https://example.com/', { muteHttpExceptions: true });
  console.log('MailApp authorized. Remaining quota: ' + quota);
  console.log('UrlFetchApp authorized. Status: ' + response.getResponseCode());
  return quota;
}

function doPost(e) {
  try {
    console.log('doPost started');
    const payload = JSON.parse(e.postData.contents || '{}');
    const expectedToken = PropertiesService.getScriptProperties().getProperty(TOKEN_PROPERTY);

    if (expectedToken && payload.token !== expectedToken) {
      console.log('invalid token');
      return jsonResponse_({ ok: false, error: 'invalid token' });
    }

    const to = String(payload.to || '').trim();
    const subject = String(payload.subject || '').trim();
    const body = String(payload.body || '');
    const filename = String(payload.filename || 'followup_high_value_unconverted.csv');
    const csvBase64 = String(payload.csvBase64 || '');

    if (!to || !subject || !csvBase64) {
      console.log('missing required field');
      return jsonResponse_({ ok: false, error: 'missing required field' });
    }

    console.log('building attachment');
    const csvBytes = Utilities.base64Decode(csvBase64);
    const attachment = Utilities.newBlob(csvBytes, 'text/csv', filename);

    console.log('sending mail to ' + to);
    MailApp.sendEmail({
      to,
      subject,
      body,
      attachments: [attachment],
    });

    console.log('mail sent');
    return jsonResponse_({ ok: true, sentTo: to, subject });
  } catch (error) {
    console.log('error: ' + String(error));
    return jsonResponse_({ ok: false, error: String(error) });
  }
}

function getParams_(e) {
  return e && e.parameter ? e.parameter : {};
}

function sendDashboardFollowup_(to, dashboardUrl) {
  const response = UrlFetchApp.fetch(dashboardUrl, { muteHttpExceptions: true });
  const html = response.getContentText('UTF-8');
  const match = html.match(/<script id="dashboard-data" type="application\/json">([\s\S]*?)<\/script>/);
  if (!match) throw new Error('dashboard-data was not found');

  const data = JSON.parse(match[1].replace(/<\\\//g, '</'));
  const month = data.latestMonth;
  const rows = ((data.byMonth[month] || {}).highValueUnconvertedRows || []).slice();
  rows.sort(function(a, b) {
    const pa = Number(a['優先度Raw'] || 99);
    const pb = Number(b['優先度Raw'] || 99);
    if (pa !== pb) return pa - pb;
    return Number(b['査定額Raw'] || 0) - Number(a['査定額Raw'] || 0);
  });

  const headers = ['優先度', 'データNo', '査定額', 'カテゴリ', '点数', '利用回数', '初回/リピート', '査定方法', 'コメント'];
  const csvLines = [headers.join(',')].concat(rows.map(function(row) {
    return headers.map(function(header) {
      return csvCell_(row[header]);
    }).join(',');
  }));
  const csv = '\uFEFF' + csvLines.join('\n');

  const priorityCounts = rows.reduce(function(acc, row) {
    const priority = String(row['優先度'] || 'C');
    acc[priority] = (acc[priority] || 0) + 1;
    return acc;
  }, {});
  const topRows = rows.slice(0, 20);
  const body = buildPlainTextBody_(month, rows, topRows);
  const htmlBody = buildHtmlBody_(month, rows, topRows, priorityCounts, dashboardUrl);

  MailApp.sendEmail({
    to,
    subject: '【自動送信】高額未成約一覧（優先度順）' + month,
    body: body,
    htmlBody: htmlBody,
    attachments: [Utilities.newBlob(csv, 'text/csv', 'followup_high_value_unconverted.csv')],
  });
  return { month: month, count: rows.length, version: APP_VERSION };
}

function buildPlainTextBody_(month, rows, topRows) {
  const lines = [
    '高額未成約一覧を優先度順で送付します。',
    '',
    '対象月: ' + month,
    '対象件数: ' + rows.length + '件',
    '条件: 未成約 / 査定額10,000円以上 / 優先度順',
    '',
    '確認ポイント:',
    '・S/Aは初回の高額案件です。優先して後追いしてください。',
    '・Bはリピーターの20,000円以上案件です。',
    '・詳細確認用のCSVを添付しています。',
    '',
    '上位20件:',
  ];
  topRows.forEach(function(row) {
    lines.push([
      row['優先度'],
      'No.' + row['データNo'],
      row['査定額'],
      row['カテゴリ'],
      row['初回/リピート'],
      row['査定方法'],
      row['コメント'],
    ].join(' / '));
  });
  lines.push('', 'CSVを添付しています。');
  return lines.join('\n');
}

function buildHtmlBody_(month, rows, topRows, priorityCounts, dashboardUrl) {
  const sCount = priorityCounts.S || 0;
  const aCount = priorityCounts.A || 0;
  const bCount = priorityCounts.B || 0;
  const cCount = priorityCounts.C || 0;
  const totalAmount = rows.reduce(function(sum, row) {
    return sum + Number(row['査定額Raw'] || 0);
  }, 0);

  const tableRows = topRows.map(function(row, index) {
    const priority = String(row['優先度'] || 'C');
    const bg = index < 5 ? '#fff1f2' : '#ffffff';
    const border = index < 5 ? '#fecdd3' : '#e5e7eb';
    return [
      '<tr style="background:' + bg + '">',
      '<td style="' + tdStyle_('center', border) + '">' + priorityBadge_(priority) + '</td>',
      '<td style="' + tdStyle_('left', border) + '">No.' + escapeHtml_(row['データNo']) + '</td>',
      '<td style="' + tdStyle_('right', border) + ';font-weight:700;color:#991b1b;">' + escapeHtml_(row['査定額']) + '</td>',
      '<td style="' + tdStyle_('left', border) + '">' + escapeHtml_(row['カテゴリ']) + '</td>',
      '<td style="' + tdStyle_('center', border) + '">' + escapeHtml_(row['初回/リピート']) + '</td>',
      '<td style="' + tdStyle_('center', border) + '">' + escapeHtml_(row['査定方法']) + '</td>',
      '<td style="' + tdStyle_('left', border) + ';line-height:1.55;">' + escapeHtml_(row['コメント']) + '</td>',
      '</tr>',
    ].join('');
  }).join('');

  return [
    '<div style="margin:0;padding:0;background:#f6f7fb;font-family:Arial,Helvetica,sans-serif;color:#111827;">',
    '<div style="max-width:960px;margin:0 auto;padding:24px;">',
    '<div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:14px;overflow:hidden;">',
    '<div style="background:#111827;color:#ffffff;padding:22px 24px;">',
    '<div style="font-size:13px;color:#cbd5e1;margin-bottom:6px;">高額未成約フォローアップ</div>',
    '<div style="font-size:22px;font-weight:700;line-height:1.35;">優先度順に確認してください</div>',
    '<div style="font-size:13px;color:#cbd5e1;margin-top:8px;">対象月 ' + escapeHtml_(month) + ' / 未成約 / 査定額10,000円以上</div>',
    '</div>',
    '<div style="padding:22px 24px;">',
    '<div style="display:block;margin-bottom:18px;">',
    metricCard_('対象件数', rows.length + '件', '#111827'),
    metricCard_('査定額合計', formatYen_(totalAmount), '#991b1b'),
    metricCard_('最優先 S/A', (sCount + aCount) + '件', '#b91c1c'),
    '</div>',
    '<div style="border:1px solid #e5e7eb;border-radius:12px;padding:16px 18px;margin-bottom:18px;background:#f9fafb;">',
    '<div style="font-size:15px;font-weight:700;margin-bottom:8px;">担当者への確認ポイント</div>',
    '<div style="font-size:14px;line-height:1.8;">',
    '1. <b>S/A</b> は初回の高額案件です。優先して後追いしてください。<br>',
    '2. <b>B</b> はリピーターの20,000円以上案件です。再提案余地を確認してください。<br>',
    '3. 詳細確認や並び替えは添付CSV、全体確認はダッシュボードを使ってください。',
    '</div>',
    '</div>',
    '<div style="margin-bottom:18px;">',
    '<span style="' + pillStyle_('#fee2e2', '#991b1b') + '">S ' + sCount + '件</span>',
    '<span style="' + pillStyle_('#ffedd5', '#9a3412') + '">A ' + aCount + '件</span>',
    '<span style="' + pillStyle_('#e0f2fe', '#075985') + '">B ' + bCount + '件</span>',
    '<span style="' + pillStyle_('#e5e7eb', '#374151') + '">C ' + cCount + '件</span>',
    '</div>',
    '<div style="font-size:16px;font-weight:700;margin-bottom:10px;">上位20件</div>',
    '<div style="overflow-x:auto;">',
    '<table style="border-collapse:collapse;width:100%;font-size:13px;">',
    '<thead>',
    '<tr style="background:#f3f4f6;color:#374151;">',
    '<th style="' + thStyle_('center') + '">優先度</th>',
    '<th style="' + thStyle_('left') + '">データNo</th>',
    '<th style="' + thStyle_('right') + '">査定額</th>',
    '<th style="' + thStyle_('left') + '">カテゴリ</th>',
    '<th style="' + thStyle_('center') + '">初回/リピート</th>',
    '<th style="' + thStyle_('center') + '">査定方法</th>',
    '<th style="' + thStyle_('left') + '">コメント</th>',
    '</tr>',
    '</thead>',
    '<tbody>',
    tableRows || '<tr><td colspan="7" style="padding:18px;text-align:center;color:#6b7280;">対象案件はありません。</td></tr>',
    '</tbody>',
    '</table>',
    '</div>',
    '<div style="margin-top:18px;font-size:13px;color:#4b5563;line-height:1.7;">CSVを添付しています。個人情報は本文に表示していません。</div>',
    '<div style="margin-top:18px;"><a href="' + escapeHtml_(dashboardUrl) + '" style="display:inline-block;background:#111827;color:#ffffff;text-decoration:none;border-radius:8px;padding:10px 14px;font-size:14px;font-weight:700;">ダッシュボードを開く</a></div>',
    '</div>',
    '</div>',
    '</div>',
    '</div>',
  ].join('');
}

function metricCard_(label, value, color) {
  return '<span style="display:inline-block;min-width:150px;margin:0 8px 8px 0;padding:12px 14px;border:1px solid #e5e7eb;border-radius:10px;background:#ffffff;">' +
    '<span style="display:block;font-size:12px;color:#6b7280;margin-bottom:4px;">' + escapeHtml_(label) + '</span>' +
    '<span style="display:block;font-size:20px;font-weight:700;color:' + color + ';">' + escapeHtml_(value) + '</span>' +
    '</span>';
}

function priorityBadge_(priority) {
  const colors = {
    S: ['#fee2e2', '#991b1b'],
    A: ['#ffedd5', '#9a3412'],
    B: ['#e0f2fe', '#075985'],
    C: ['#e5e7eb', '#374151'],
  };
  const color = colors[priority] || colors.C;
  return '<span style="' + pillStyle_(color[0], color[1]) + '">' + escapeHtml_(priority) + '</span>';
}

function pillStyle_(background, color) {
  return 'display:inline-block;border-radius:999px;padding:4px 9px;margin:0 6px 6px 0;background:' + background + ';color:' + color + ';font-weight:700;font-size:12px;';
}

function thStyle_(align) {
  return 'padding:10px 12px;border-bottom:1px solid #d1d5db;text-align:' + align + ';white-space:nowrap;';
}

function tdStyle_(align, border) {
  return 'padding:10px 12px;border-bottom:1px solid ' + border + ';text-align:' + align + ';vertical-align:top;';
}

function formatYen_(value) {
  return Number(value || 0).toLocaleString('ja-JP') + '円';
}

function escapeHtml_(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function csvCell_(value) {
  const text = String(value == null ? '' : value);
  return /[",\r\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
}

function jsonResponse_(data) {
  return ContentService
    .createTextOutput(JSON.stringify(data))
    .setMimeType(ContentService.MimeType.JSON);
}
