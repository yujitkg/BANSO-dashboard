# 査定分析ダッシュボード

GitHub Pages公開用の単体HTMLダッシュボードです。

公開対象:

- `index.html`
- `.nojekyll`

元データや生成物フォルダは `.gitignore` で除外しています。

## 別PCで使う場合

1. GitHub Desktopでこのリポジトリをcloneします。
2. Python 3をインストールします。
3. `別PCセットアップ.bat` を実行します。
4. 詳細は `OTHER_PC_SETUP.md` を確認してください。

## よく使うバッチ

- 当月分を取得して送信: `査定データ取得から更新.bat`
- 指定年月を取得して送信: `指定年月の査定データ取得から送信.bat`
