# Google Apps Script メール送信セットアップ

## 1. Apps Scriptを作る、または既存GASを更新する

1. https://script.google.com/ を開く
2. `新しいプロジェクト` を押す
3. PC側で `copy_gas_code.bat` をダブルクリックする。日本語名のbatがよければ `GASコードをコピー.bat` でも同じです。
4. Apps Script側のコードをすべて置き換えて貼り付ける
6. 保存する
7. プロジェクト設定、またはスクリプトプロパティに `FOLLOWUP_MAIL_TOKEN` を追加する
8. 値には任意の合言葉を入れる
9. 関数選択で `authorizeMailApp` を選び、`実行` を押して権限承認する

## 2. Webアプリとしてデプロイ

1. 右上の `デプロイ` → `新しいデプロイ`
2. 種類は `ウェブアプリ`
3. 実行ユーザーは `自分`
4. アクセスできるユーザーは `全員`
5. デプロイして、表示されたWebアプリURLを控える

既存GASを更新する場合は、保存後に必ず `デプロイ` → `デプロイを管理` → 鉛筆マーク → `新バージョン` → `デプロイ` を実行する。保存だけではWebアプリに反映されません。

`UrlFetchApp.fetch を呼び出す権限がありません` と出た場合は、Apps Script画面で `authorizeMailApp` を選んで実行し、権限承認後に新バージョンで再デプロイする。

## 3. PC側の設定

`メール送信設定.bat` をダブルクリックする。

表示されたら、次の4つを入力する。

- WebアプリURL
- 送信先メールアドレス。空欄なら `takagi@y-takumi.jp`
- スクリプトプロパティに入れた合言葉
- ダッシュボードURL。空欄なら公開ページURL

```json
{
  "WebAppUrl": "控えたWebアプリURL",
  "To": "takagi@y-takumi.jp",
  "Token": "スクリプトプロパティに入れた合言葉",
  "DashboardUrl": "https://yujitkg.github.io/BANSO-dashboard/?v=mail"
}
```

`followup_mail_config.json` はGitに入らない設定です。

## 4. 実行

1. `mail_automation_check.bat` を実行する。日本語名のbatがよければ `メール自動化チェック.bat` でも同じです。
2. 接続テストとメール送信テストが成功することを確認する
3. `dashboard_update.bat` を実行する。日本語名のbatがよければ `ダッシュボード更新.bat` でも同じです。

`dashboard_update.bat` を実行すると、ダッシュボード更新後にGAS経由で高額未成約一覧メールを送信します。
