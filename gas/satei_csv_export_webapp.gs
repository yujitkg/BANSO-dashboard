const SATEI_EXPORT_TOKEN_PROPERTY = 'SATEI_EXPORT_TOKEN';
const SATEI_EXPORT_VERSION = '2026-07-01-csv-export-v1';

function doGet(e) {
  try {
    const params = e && e.parameter ? e.parameter : {};
    const action = String(params.action || 'status');
    const expectedToken = PropertiesService.getScriptProperties().getProperty(SATEI_EXPORT_TOKEN_PROPERTY);

    if (expectedToken && action !== 'status' && params.token !== expectedToken) {
      return sateiExportJson_({ ok: false, error: 'invalid token' });
    }

    const month = String(params.month || '').trim() || Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM');

    if (action === 'startThisMonthFetch') {
      pasteSateiCsvToSheetsByMonth_(month, false);
      startAutoFetchAllDetailsLater_();
      return sateiExportJson_({
        ok: true,
        action: action,
        month: month,
        message: 'fetch started',
      });
    }

    if (action === 'progress') {
      return sateiExportJson_(buildSateiFetchProgress_(month));
    }

    if (action === 'exportCsvJson') {
      return sateiExportJson_(buildSateiCsvExportPayload_(month));
    }

    return sateiExportJson_({
      ok: true,
      app: 'satei_csv_export_webapp',
      version: SATEI_EXPORT_VERSION,
      actions: ['status', 'startThisMonthFetch', 'progress', 'exportCsvJson'],
      time: new Date().toISOString(),
    });
  } catch (error) {
    return sateiExportJson_({ ok: false, error: String(error) });
  }
}

function buildSateiFetchProgress_(month) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName('査定明細取得キュー');

  if (!sheet) {
    return {
      ok: true,
      version: SATEI_EXPORT_VERSION,
      month: month,
      running: false,
      total: 0,
      done: 0,
      error: 0,
      remaining: 0,
      ready: false,
      message: 'queue sheet was not found',
    };
  }

  const values = sheet.getDataRange().getValues();
  let total = 0;
  let done = 0;
  let error = 0;
  let remaining = 0;

  for (let i = 1; i < values.length; i++) {
    const targetMonth = String(values[i][5] || '');
    if (targetMonth && targetMonth !== month) continue;

    total++;
    const status = String(values[i][3] || '');
    if (status === 'DONE') {
      done++;
    } else if (status === 'ERROR') {
      error++;
    } else {
      remaining++;
    }
  }

  const running = PropertiesService.getScriptProperties().getProperty('DETAIL_AUTO_RUNNING') === '1';
  return {
    ok: true,
    version: SATEI_EXPORT_VERSION,
    month: month,
    running: running,
    total: total,
    done: done,
    error: error,
    remaining: remaining,
    ready: total > 0 && remaining === 0 && !running,
    checkedAt: Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM-dd HH:mm:ss'),
  };
}

function buildSateiCsvExportPayload_(month) {
  const sheetNames = [
    '成約済み',
    '未成約',
    '成約済み_明細',
    '未成約_明細',
  ];

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const files = sheetNames.map(function(sheetName) {
    const sheet = ss.getSheetByName(sheetName);
    if (!sheet) {
      throw new Error('sheet was not found: ' + sheetName);
    }

    const values = sheet.getDataRange().getValues();
    const csv = '\uFEFF' + sateiValuesToCsv_(values);
    return {
      name: sheetName + '.csv',
      contentBase64: Utilities.base64Encode(Utilities.newBlob(csv, 'text/csv').getBytes()),
      rowCount: Math.max(values.length - 1, 0),
    };
  });

  return {
    ok: true,
    version: SATEI_EXPORT_VERSION,
    month: month,
    files: files,
    exportedAt: Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM-dd HH:mm:ss'),
  };
}

function sateiValuesToCsv_(values) {
  return values.map(function(row) {
    return row.map(function(cell) {
      const text = String(cell == null ? '' : cell);
      return '"' + text.replace(/"/g, '""') + '"';
    }).join(',');
  }).join('\r\n');
}

function sateiExportJson_(data) {
  return ContentService
    .createTextOutput(JSON.stringify(data))
    .setMimeType(ContentService.MimeType.JSON);
}
