# 別PCセットアップ手順

別PCでも同じ自動化を使えます。最初に1回だけ設定してください。

## 必要なもの

- GitHub Desktop
- Python 3
- Google Chromeなどのブラウザ
- GitHubへpushできるアカウント
- GASのWebアプリURLとToken

## 手順

1. GitHub Desktopで `BANSO-dashboard` をcloneします。
2. cloneしたフォルダを開きます。
3. `別PCセットアップ.bat` を実行します。
4. 画面の質問に沿って、以下を入力します。
   - BANSOデータ取得GASのWebアプリURL
   - `SATEI_EXPORT_TOKEN`
   - CSV保存先。空欄なら `BANSO-dashboard\data`
   - メール送信用GASのWebアプリURL
   - 送信先メールアドレス。通常は `renraku@y-takumi.jp`
   - `FOLLOWUP_MAIL_TOKEN`
5. GitHub Desktopでこのリポジトリを開き、pushできることを確認します。

## 使い方

- 当月分を取得して送信: `査定データ取得から更新.bat`
- 指定年月を取得して送信: `指定年月の査定データ取得から送信.bat`

指定年月は `2026-06` のように入力します。

## よくある原因

- Pythonが見つからない場合: Python 3をインストールし、PATHに追加します。
- GASがJSONを返さない場合: Webアプリの公開設定を確認します。
- pushに失敗する場合: GitHub Desktopでログイン状態とremoteを確認します。
- CSV保存先を変えたい場合: `satei_auto_config.json` の `DataRoot` を変更します。通常は `BANSO-dashboard\data` のままでOKです。
