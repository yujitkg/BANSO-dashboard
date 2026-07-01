const TOKEN_PROPERTY = 'FOLLOWUP_MAIL_TOKEN';
const APP_VERSION = '2026-06-30-get-mail-v2';

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

  const bodyLines = [
    '高額未成約一覧を優先度順で送付します。',
    '',
    '対象月: ' + month,
    '対象件数: ' + rows.length + '件',
    '条件: 未成約 / 査定額10,000円以上 / 優先度順',
    '',
    '上位20件:',
  ];
  rows.slice(0, 20).forEach(function(row) {
    bodyLines.push([
      row['優先度'],
      'No.' + row['データNo'],
      row['査定額'],
      row['カテゴリ'],
      row['初回/リピート'],
      row['査定方法'],
      row['コメント'],
    ].join(' / '));
  });
  bodyLines.push('', 'CSVを添付しています。');

  MailApp.sendEmail({
    to,
    subject: '【自動送信】高額未成約一覧（優先度順）' + month,
    body: bodyLines.join('\n'),
    attachments: [Utilities.newBlob(csv, 'text/csv', 'followup_high_value_unconverted.csv')],
  });
  return { month: month, count: rows.length, version: APP_VERSION };
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
