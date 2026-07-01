const BASE_URL = 'https://member.banso.biz/admin/satei/';
const LIST_URL = BASE_URL + 'list.php';
const CSV_URL  = BASE_URL + 'export_csv.php';

const SHEET_SEIYAKU = '成約済み';
const SHEET_MISEIYAKU = '未成約';
const SHEET_SEIYAKU_DETAIL = '成約済み_明細';
const SHEET_MISEIYAKU_DETAIL = '未成約_明細';
const SHEET_DETAIL_QUEUE = '査定明細取得キュー';

const DETAIL_BATCH_SIZE = 25;

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('BANSO査定取得')
    .addItem('当月分：一覧＋明細を自動取得', 'runThisMonthSateiFullAuto')
    .addItem('4シートをCSV出力', 'exportFourSheetsAsCsvFiles')
    .addItem('年月指定：一覧＋明細を自動取得', 'runSateiFullAutoByInputMonth')
    .addSeparator()
    .addItem('明細自動取得の進捗を確認', 'checkDetailFetchProgress')
    .addItem('明細自動取得を停止', 'stopAutoFetchDetails')
    .addSeparator()
    .addItem('当月分一覧のみ取得', 'pasteThisMonthSateiCsvToSheets')
    .addItem('年月指定で一覧のみ取得', 'pasteSateiCsvByInputMonth')
    .addSeparator()
    .addItem('明細を自動で最後まで取得', 'startAutoFetchAllDetailsLater')
    .addSeparator()
    .addItem('成約済み明細を手動で続きから取得', 'fetchSeiyakuDetailsResume')
    .addItem('未成約明細を手動で続きから取得', 'fetchMiseiyakuDetailsResume')
    .addToUi();
}

function runThisMonthSateiFullAuto() {
  const targetMonth = Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM');

  pasteSateiCsvToSheetsByMonth_(targetMonth, false);
  startAutoFetchAllDetailsLater_();

  SpreadsheetApp.getUi().alert(
    '一覧取得が完了しました。\n\n明細取得は約1分後から自動で開始されます。'
  );
}

function runSateiFullAutoByInputMonth() {
  const ui = SpreadsheetApp.getUi();

  const res = ui.prompt(
    '年月指定：一覧＋明細を自動取得',
    '取得したい年月を YYYY-MM 形式で入力してください。例：2026-05',
    ui.ButtonSet.OK_CANCEL
  );

  if (res.getSelectedButton() !== ui.Button.OK) return;

  const targetMonth = res.getResponseText().trim();

  if (!/^\d{4}-\d{2}$/.test(targetMonth)) {
    ui.alert('入力形式が違います。例：2026-05 の形式で入力してください。');
    return;
  }

  // 一覧取得
  pasteSateiCsvToSheetsByMonth_(targetMonth, false);

  // 自動取得フラグON
  PropertiesService.getScriptProperties().setProperty(
    'DETAIL_AUTO_RUNNING',
    '1'
  );

  // 既存トリガー削除
  deleteTriggers_('autoFetchSeiyakuDetails');
  deleteTriggers_('autoFetchMiseiyakuDetails');

  // 1分後開始予約
  ScriptApp.newTrigger('autoFetchSeiyakuDetails')
    .timeBased()
    .after(60 * 1000)
    .create();

  ui.alert(
    '一覧取得が完了しました。\n\n' +
    '約1分後から明細取得が自動で開始され、最後まで自動実行されます。'
  );
}

function pasteThisMonthSateiCsvToSheets() {
  const targetMonth = Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM');
  pasteSateiCsvToSheetsByMonth_(targetMonth, true);
}

function pasteSateiCsvByInputMonth() {
  const ui = SpreadsheetApp.getUi();

  const res = ui.prompt(
    '年月を指定して一覧のみ取得',
    '取得したい年月を YYYY-MM 形式で入力してください。例：2026-05',
    ui.ButtonSet.OK_CANCEL
  );

  if (res.getSelectedButton() !== ui.Button.OK) return;

  const targetMonth = res.getResponseText().trim();

  if (!/^\d{4}-\d{2}$/.test(targetMonth)) {
    ui.alert('入力形式が違います。例：2026-05 の形式で入力してください。');
    return;
  }

  pasteSateiCsvToSheetsByMonth_(targetMonth, true);
}

function pasteSateiCsvToSheetsByMonth_(targetMonth, showAlert) {
  stopAutoFetchDetailsSilent_();

  const cookie = loginBanso_();

  const seiyakuIds = [];
  const miseiyakuIds = [];
  const queueRows = [];

  const idSet = {};
  let page = 1;

  while (true) {
    const searchUrl =
      LIST_URL +
      '?p=' + page +
      '&n=' +
      '&o=' +
      '&d=' +
      '&shop_id=' +
      '&order_date=' + encodeURIComponent(targetMonth) +
      '&oid=' +
      '&nickname=' +
      '&order_cat=' +
      '&tel=' +
      '&email=' +
      '&lstep_id=' +
      '&time_t=' +
      '&de_memo=' +
      '&contact=' +
      '&campaign=' +
      '&arrival_done=' +
      '&m_rpa=' +
      '&satei0_flag=' +
      '&status=' +
      '&type=' +
      '&btnSearch=' + encodeURIComponent('検索');

    const listRes = UrlFetchApp.fetch(searchUrl, {
      method: 'get',
      headers: { Cookie: cookie },
      followRedirects: true,
      muteHttpExceptions: true
    });

    const html = listRes.getContentText('UTF-8');
    const rows = html.match(/<tr[\s\S]*?<\/tr>/gi) || [];

    let pageIdCount = 0;

    rows.forEach(rowHtml => {
      const idMatch = rowHtml.match(/<input[^>]*name=["']check["'][^>]*value=["']?(\d+)["']?/i);
      if (!idMatch) return;

      const id = idMatch[1];
      if (idSet[id]) return;

      idSet[id] = true;
      pageIdCount++;

      const plainText = htmlToText_(rowHtml).replace(/\s+/g, '');

      const isSeiyaku =
        plainText.includes('L到着買取済') ||
        plainText.includes('到着買取済');

      const statusName = isSeiyaku ? '成約済み' : '未成約';

      if (isSeiyaku) {
        seiyakuIds.push(id);
      } else {
        miseiyakuIds.push(id);
      }

      const detailUrl = getDetailUrlFromRow_(rowHtml, id);

      queueRows.push([
        id,
        statusName,
        detailUrl,
        '',
        '',
        targetMonth
      ]);
    });

    Logger.log('page=' + page + ' 取得件数: ' + pageIdCount);

    if (pageIdCount === 0) break;

    page++;
    if (page > 50) break;
  }

  pasteCsvByIdsToSheet_(cookie, seiyakuIds, SHEET_SEIYAKU);
  pasteCsvByIdsToSheet_(cookie, miseiyakuIds, SHEET_MISEIYAKU);

  pasteDetailQueue_(queueRows);
  resetDetailSheet_(SHEET_SEIYAKU_DETAIL);
  resetDetailSheet_(SHEET_MISEIYAKU_DETAIL);

  if (showAlert) {
    SpreadsheetApp.getUi().alert(
      '一覧取得が完了しました。\n\n' +
      '成約済み件数: ' + seiyakuIds.length + '件\n' +
      '未成約件数: ' + miseiyakuIds.length + '件\n' +
      '明細キュー件数: ' + queueRows.length + '件'
    );
  }
}

function startAutoFetchAllDetailsLater() {
  startAutoFetchAllDetailsLater_();
  SpreadsheetApp.getUi().alert(
    '明細の自動取得を予約しました。\n\n約1分後から自動で開始されます。'
  );
}

function startAutoFetchAllDetailsLater_() {
  deleteTriggers_('autoFetchSeiyakuDetails');
  deleteTriggers_('autoFetchMiseiyakuDetails');

  PropertiesService.getScriptProperties().setProperty('DETAIL_AUTO_RUNNING', '1');

  createNextTrigger_('autoFetchSeiyakuDetails');
}

function stopAutoFetchDetails() {
  stopAutoFetchDetailsSilent_();
  SpreadsheetApp.getUi().alert('明細の自動取得を停止しました。');
}

function stopAutoFetchDetailsSilent_() {
  PropertiesService.getScriptProperties().deleteProperty('DETAIL_AUTO_RUNNING');
  deleteTriggers_('autoFetchSeiyakuDetails');
  deleteTriggers_('autoFetchMiseiyakuDetails');
}

function autoFetchSeiyakuDetails() {
  if (!isAutoRunning_()) return;

  deleteTriggers_('autoFetchSeiyakuDetails');

  const remaining = fetchDetailsResumeByStatusCore_('成約済み', SHEET_SEIYAKU_DETAIL);

  if (remaining > 0) {
    createNextTrigger_('autoFetchSeiyakuDetails');
  } else {
    createNextTrigger_('autoFetchMiseiyakuDetails');
  }
}

function autoFetchMiseiyakuDetails() {
  if (!isAutoRunning_()) return;

  deleteTriggers_('autoFetchMiseiyakuDetails');

  const remaining = fetchDetailsResumeByStatusCore_('未成約', SHEET_MISEIYAKU_DETAIL);

  if (remaining > 0) {
    createNextTrigger_('autoFetchMiseiyakuDetails');
  } else {
    stopAutoFetchDetailsSilent_();
    Logger.log('明細の自動取得がすべて完了しました。');
  }
}

function isAutoRunning_() {
  return PropertiesService.getScriptProperties().getProperty('DETAIL_AUTO_RUNNING') === '1';
}

function createNextTrigger_(functionName) {
  deleteTriggers_(functionName);

  ScriptApp.newTrigger(functionName)
    .timeBased()
    .after(60 * 1000)
    .create();
}

function deleteTriggers_(functionName) {
  const triggers = ScriptApp.getProjectTriggers();

  triggers.forEach(trigger => {
    if (trigger.getHandlerFunction() === functionName) {
      ScriptApp.deleteTrigger(trigger);
    }
  });
}

function checkDetailFetchProgress() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(SHEET_DETAIL_QUEUE);

  if (!sheet) {
    SpreadsheetApp.getUi().alert('査定明細取得キューがありません。');
    return;
  }

  const values = sheet.getDataRange().getValues();

  let seiyakuDone = 0;
  let seiyakuError = 0;
  let seiyakuRemaining = 0;

  let miseiyakuDone = 0;
  let miseiyakuError = 0;
  let miseiyakuRemaining = 0;

  for (let i = 1; i < values.length; i++) {
    const statusName = values[i][1];
    const done = values[i][3];

    if (statusName === '成約済み') {
      if (done === 'DONE') seiyakuDone++;
      else if (done === 'ERROR') seiyakuError++;
      else seiyakuRemaining++;
    }

    if (statusName === '未成約') {
      if (done === 'DONE') miseiyakuDone++;
      else if (done === 'ERROR') miseiyakuError++;
      else miseiyakuRemaining++;
    }
  }

  const autoRunning =
    PropertiesService.getScriptProperties().getProperty('DETAIL_AUTO_RUNNING') === '1'
      ? '起動中'
      : '停止中';

  const triggers = ScriptApp.getProjectTriggers()
    .map(t => t.getHandlerFunction())
    .filter(name =>
      name === 'autoFetchSeiyakuDetails' ||
      name === 'autoFetchMiseiyakuDetails'
    );

  const triggerStatus = triggers.length > 0
    ? triggers.join('\n')
    : '予約トリガーなし';

  SpreadsheetApp.getUi().alert(
    '明細自動取得の進捗\n\n' +
    '自動取得状態: ' + autoRunning + '\n' +
    '予約トリガー:\n' + triggerStatus + '\n\n' +
    '【成約済み】\n' +
    '取得済み: ' + seiyakuDone + '件\n' +
    'エラー: ' + seiyakuError + '件\n' +
    '残り: ' + seiyakuRemaining + '件\n\n' +
    '【未成約】\n' +
    '取得済み: ' + miseiyakuDone + '件\n' +
    'エラー: ' + miseiyakuError + '件\n' +
    '残り: ' + miseiyakuRemaining + '件'
  );
}

function fetchSeiyakuDetailsResume() {
  const remaining = fetchDetailsResumeByStatusCore_('成約済み', SHEET_SEIYAKU_DETAIL);
  SpreadsheetApp.getUi().alert('成約済み明細を取得しました。\n残り件数: ' + remaining + '件');
}

function fetchMiseiyakuDetailsResume() {
  const remaining = fetchDetailsResumeByStatusCore_('未成約', SHEET_MISEIYAKU_DETAIL);
  SpreadsheetApp.getUi().alert('未成約明細を取得しました。\n残り件数: ' + remaining + '件');
}

function fetchDetailsResumeByStatusCore_(statusName, sheetName) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const queueSheet = ss.getSheetByName(SHEET_DETAIL_QUEUE);

  if (!queueSheet) {
    Logger.log('明細取得キューがありません。');
    return 0;
  }

  const values = queueSheet.getDataRange().getValues();

  if (values.length <= 1) {
    Logger.log('明細取得キューにデータがありません。');
    return 0;
  }

  const cookie = loginBanso_();

  let processed = 0;
  const appendedRows = [];

  for (let i = 1; i < values.length; i++) {
    if (processed >= DETAIL_BATCH_SIZE) break;

    const row = values[i];

    const dataNo = row[0];
    const rowStatus = row[1];
    const detailUrl = row[2];
    const done = row[3];

    if (rowStatus !== statusName) continue;
    if (done === 'DONE' || done === 'ERROR') continue;

    if (!detailUrl) {
      queueSheet.getRange(i + 1, 4).setValue('ERROR');
      queueSheet.getRange(i + 1, 5).setValue('詳細URLなし');
      processed++;
      continue;
    }

    try {
      const detailRows = fetchDetailRows_(cookie, detailUrl, dataNo, statusName);

      if (detailRows.length > 0) {
        appendedRows.push(...detailRows);
      }

      queueSheet.getRange(i + 1, 4).setValue('DONE');
      queueSheet.getRange(i + 1, 5).setValue(
        Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM-dd HH:mm:ss')
      );

      processed++;

    } catch (e) {
      queueSheet.getRange(i + 1, 4).setValue('ERROR');
      queueSheet.getRange(i + 1, 5).setValue(String(e));
      processed++;
    }
  }

  if (appendedRows.length > 0) {
    appendDetailsToSheet_(sheetName, appendedRows);
  }

  const remaining = countRemainingQueue_(statusName);

  Logger.log(statusName + ' 今回処理件数: ' + processed);
  Logger.log(statusName + ' 今回追加明細行: ' + appendedRows.length);
  Logger.log(statusName + ' 残り件数: ' + remaining);

  return remaining;
}

function countRemainingQueue_(statusName) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(SHEET_DETAIL_QUEUE);
  if (!sheet) return 0;

  const values = sheet.getDataRange().getValues();
  let count = 0;

  for (let i = 1; i < values.length; i++) {
    if (
      values[i][1] === statusName &&
      values[i][3] !== 'DONE' &&
      values[i][3] !== 'ERROR'
    ) {
      count++;
    }
  }

  return count;
}

function pasteDetailQueue_(queueRows) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  let sheet = ss.getSheetByName(SHEET_DETAIL_QUEUE);
  if (!sheet) sheet = ss.insertSheet(SHEET_DETAIL_QUEUE);

  sheet.clearContents();

  const header = [
    'データNo',
    '成約区分',
    '詳細URL',
    '取得状況',
    '取得日時またはエラー',
    '対象年月'
  ];

  const output = [header, ...queueRows];

  sheet.getRange(1, 1, output.length, output[0].length).setNumberFormat('@');
  sheet.getRange(1, 1, output.length, output[0].length).setValues(output);
}

function resetDetailSheet_(sheetName) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  let sheet = ss.getSheetByName(sheetName);
  if (!sheet) sheet = ss.insertSheet(sheetName);

  sheet.clearContents();

  const header = getDetailHeader_();
  sheet.getRange(1, 1, 1, header.length).setNumberFormat('@');
  sheet.getRange(1, 1, 1, header.length).setValues([header]);
}

function appendDetailsToSheet_(sheetName, detailRows) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  let sheet = ss.getSheetByName(sheetName);
  if (!sheet) {
    sheet = ss.insertSheet(sheetName);
    const header = getDetailHeader_();
    sheet.getRange(1, 1, 1, header.length).setNumberFormat('@');
    sheet.getRange(1, 1, 1, header.length).setValues([header]);
  }

  if (detailRows.length === 0) return;

  const startRow = sheet.getLastRow() + 1;
  sheet.getRange(startRow, 1, detailRows.length, detailRows[0].length).setNumberFormat('@');
  sheet.getRange(startRow, 1, detailRows.length, detailRows[0].length).setValues(detailRows);
}

function getDetailHeader_() {
  return [
    'データNo',
    '成約区分',
    '作業',
    'カテゴリ',
    'JANコード',
    'メーカー',
    '商品名',
    'セット',
    '商品備考',
    '購入時期',
    '品質期限',
    '種別',
    '単価',
    '数量',
    '小計',
    '条件1',
    '条件2',
    '付与PT',
    'スタート価格',
    '社内向けコメント',
    '定価税抜'
  ];
}

function pasteCsvByIdsToSheet_(cookie, ids, sheetName) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  let sheet = ss.getSheetByName(sheetName);
  if (!sheet) sheet = ss.insertSheet(sheetName);

  sheet.clearContents();

  if (ids.length === 0) {
    sheet.getRange(1, 1).setValue(sheetName + 'のデータはありません');
    return;
  }

  const allRows = [];
  let header = null;

  const chunks = chunkArray_(ids, 80);

  chunks.forEach(chunk => {
    const csvUrl = CSV_URL + '?sid=' + encodeURIComponent(chunk.join(','));

    const csvRes = UrlFetchApp.fetch(csvUrl, {
      method: 'get',
      headers: { Cookie: cookie },
      followRedirects: true,
      muteHttpExceptions: true
    });

    const csvText = csvRes.getContentText('Shift_JIS');
    const rows = Utilities.parseCsv(csvText);

    if (rows.length === 0) return;

    const currentHeader = rows.shift();

    if (!header) header = currentHeader;

    allRows.push(...rows);
  });

  if (!header) {
    sheet.getRange(1, 1).setValue('CSVの取得に失敗しました');
    return;
  }

  const noIndex = header.findIndex(h => String(h).includes('データNo'));

  if (noIndex !== -1) {
    allRows.sort((a, b) => Number(a[noIndex]) - Number(b[noIndex]));
  }

  const output = [header, ...allRows];

  sheet.getRange(1, 1, output.length, output[0].length).setNumberFormat('@');
  sheet.getRange(1, 1, output.length, output[0].length).setValues(output);
}

function getDetailUrlFromRow_(rowHtml, id) {
  const links = [];
  const regex = /<a[^>]+href=["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi;
  let match;

  while ((match = regex.exec(rowHtml)) !== null) {
    const href = match[1];
    const text = htmlToText_(match[2]);

    if (href.includes('docs.google.com')) continue;

    links.push({
      href: href,
      text: text
    });
  }

  for (let i = 0; i < links.length; i++) {
    const textPlain = links[i].text.replace(/\s+/g, '');

    if (
      textPlain.includes('No.' + id) ||
      textPlain.includes('No．' + id) ||
      textPlain.includes(String(id))
    ) {
      return toAbsoluteUrl_(links[i].href);
    }
  }

  for (let i = 0; i < links.length; i++) {
    const href = links[i].href;

    if (
      href.includes('detail') ||
      href.includes('edit') ||
      href.includes('input') ||
      href.includes('satei') ||
      href.includes('order')
    ) {
      return toAbsoluteUrl_(href);
    }
  }

  return '';
}

function fetchDetailRows_(cookie, detailUrl, dataNo, statusName) {
  const res = UrlFetchApp.fetch(detailUrl, {
    method: 'get',
    headers: { Cookie: cookie },
    followRedirects: true,
    muteHttpExceptions: true
  });

  const html = res.getContentText('UTF-8');

  const detailRows = extractSateiDetailRows_(html, dataNo, statusName);

  Logger.log('No.' + dataNo + ' 明細取得件数: ' + detailRows.length);

  return detailRows;
}

function extractSateiDetailRows_(html, dataNo, statusName) {
  const results = [];

  const tables = html.match(/<table[\s\S]*?<\/table>/gi) || [];

  let detailTable = '';

  tables.forEach(tableHtml => {
    const text = htmlToText_(tableHtml);

    if (
      text.includes('JANコード') &&
      text.includes('メーカー') &&
      text.includes('商品名') &&
      text.includes('単価') &&
      text.includes('数量')
    ) {
      detailTable = tableHtml;
    }
  });

  if (!detailTable) {
    Logger.log('No.' + dataNo + ' 明細テーブルが見つかりません');
    return results;
  }

  const trList = detailTable.match(/<tr[\s\S]*?<\/tr>/gi) || [];

  trList.forEach(trHtml => {
    const cells = extractCells_(trHtml);

    if (cells.length < 8) return;

    const joined = cells.join('');

    if (
      joined.includes('作業') &&
      joined.includes('カテゴリ') &&
      joined.includes('JANコード')
    ) {
      return;
    }

    if (
      joined.includes('全選択') ||
      joined.includes('商品削除') ||
      joined.includes('査定額小計') ||
      joined.includes('チェックした項目')
    ) {
      return;
    }

    const row = normalizeDetailCells_(cells);

    const jan = row[2] || '';
    const maker = row[3] || '';
    const itemName = row[4] || '';

    if (
      !String(jan).trim() &&
      !String(maker).trim() &&
      !String(itemName).trim()
    ) {
      return;
    }

    results.push([
      dataNo,
      statusName,
      ...row
    ]);
  });

  return results;
}

function normalizeDetailCells_(cells) {
  const row = [];

  for (let i = 0; i < 19; i++) {
    row.push(cells[i] || '');
  }

  return row;
}

function extractCells_(trHtml) {
  const cells = [];
  const regex = /<(td|th)[^>]*>([\s\S]*?)<\/\1>/gi;
  let match;

  while ((match = regex.exec(trHtml)) !== null) {
    cells.push(htmlToText_(match[2]).trim());
  }

  return cells;
}

function htmlToText_(html) {
  return String(html)
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/<style[\s\S]*?<\/style>/gi, '')
    .replace(/<select[\s\S]*?<\/select>/gi, function(selectHtml) {
      const selected = selectHtml.match(/<option[^>]*selected[^>]*>([\s\S]*?)<\/option>/i);
      if (selected) return selected[1];

      const first = selectHtml.match(/<option[^>]*>([\s\S]*?)<\/option>/i);
      return first ? first[1] : '';
    })
    .replace(/<input[^>]*value=["']([^"']*)["'][^>]*>/gi, '$1')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\r?\n/g, ' ')
    .replace(/[ \t]+/g, ' ')
    .trim();
}

function toAbsoluteUrl_(url) {
  if (!url) return '';

  if (url.startsWith('http://') || url.startsWith('https://')) {
    return url;
  }

  if (url.startsWith('/')) {
    return 'https://member.banso.biz' + url;
  }

  return BASE_URL + url;
}

function chunkArray_(array, size) {
  const result = [];

  for (let i = 0; i < array.length; i += size) {
    result.push(array.slice(i, i + size));
  }

  return result;
}

function loginBanso_() {
  const loginUrl = 'https://member.banso.biz/admin/login.php';

  const payload = {
    loginid: PropertiesService.getScriptProperties().getProperty('BANSO_ID'),
    loginpwd: PropertiesService.getScriptProperties().getProperty('BANSO_PASS'),
    login: 'ログイン'
  };

  const res = UrlFetchApp.fetch(loginUrl, {
    method: 'post',
    payload: payload,
    followRedirects: false,
    muteHttpExceptions: true
  });

  const headers = res.getAllHeaders();
  const setCookie = headers['Set-Cookie'] || headers['set-cookie'];

  if (!setCookie) {
    throw new Error('ログインCookieが取得できませんでした。ID・パスワード、またはログインURLを確認してください。');
  }

  if (Array.isArray(setCookie)) {
    return setCookie.map(c => c.split(';')[0]).join('; ');
  }

  return setCookie.split(';')[0];
}
const EXPORT_FOLDER_NAME = 'BANSO_CSV_EXPORT';

function exportFourSheetsAsCsvFiles() {
  const sheetNames = [
    '成約済み',
    '未成約',
    '成約済み_明細',
    '未成約_明細'
  ];

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const folder = getOrCreateFolder_(EXPORT_FOLDER_NAME);

  const timestamp = Utilities.formatDate(
    new Date(),
    'Asia/Tokyo',
    'yyyyMMdd_HHmmss'
  );

  const exportFolder = folder.createFolder('BANSO_export_' + timestamp);

  sheetNames.forEach(sheetName => {
    const sheet = ss.getSheetByName(sheetName);

    if (!sheet) return;

    const values = sheet.getDataRange().getValues();

    if (values.length === 0) return;

    const csv = valuesToCsv_(values);

    exportFolder.createFile(
      sheetName + '.csv',
      csv,
      MimeType.CSV
    );
  });

  SpreadsheetApp.getUi().alert(
    'CSV出力が完了しました。\n\n保存先フォルダ：' + exportFolder.getName()
  );
}

function valuesToCsv_(values) {
  return values.map(row => {
    return row.map(cell => {
      const text = String(cell ?? '');

      const escaped = text.replace(/"/g, '""');

      return '"' + escaped + '"';
    }).join(',');
  }).join('\r\n');
}

function getOrCreateFolder_(folderName) {
  const folders = DriveApp.getFoldersByName(folderName);

  if (folders.hasNext()) {
    return folders.next();
  }

  return DriveApp.createFolder(folderName);
}

// ---- Web app automation endpoint ----
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

