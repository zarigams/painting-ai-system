@echo off
chcp 65001 >nul
title AI積算・見積りシステム

echo.
echo  ============================================
echo   塗装会社専用 AI積算・見積りシステム
echo  ============================================
echo.

:: このバッチファイルの場所を取得
cd /d "%~dp0"

:: Pythonの確認
python --version >nul 2>&1
if errorlevel 1 (
    echo [エラー] Pythonが見つかりません。
    echo Python 3.10以上をインストールしてください。
    echo https://www.python.org/downloads/
    pause
    exit /b 1
)

:: streamlitの確認・インストール
python -m streamlit --version >nul 2>&1
if errorlevel 1 (
    echo [初回セットアップ] 必要なパッケージをインストールします...
    echo （1〜3分かかります）
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [エラー] パッケージのインストールに失敗しました。
        pause
        exit /b 1
    )
    echo.
    echo インストール完了！
)

:: .envファイルの確認
if not exist ".env" (
    echo [注意] .envファイルが見つかりません。
    echo .env.example をコピーして .env を作成し、
    echo OpenAI APIキーを設定してください。
    echo.
    copy .env.example .env >nul
    echo .envファイルを作成しました。メモ帳で開きます...
    notepad .env
    echo.
    echo APIキーを設定後、このファイルを再度実行してください。
    pause
    exit /b 0
)

:: ブラウザで開く
echo ブラウザを起動します...
echo アプリURL: http://localhost:8501
echo.
echo ※ 終了するにはこのウィンドウを閉じてください
echo.

:: Streamlit起動
python -m streamlit run app.py --server.headless false --browser.gatherUsageStats false

pause
