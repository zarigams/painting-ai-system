# 塗装会社専用 AI積算・見積りシステム

## システム概要

営業担当が現場から帰社する頃には見積書の8割が完成している状態を目指すシステムです。

```
現場で写真撮影 → 音声/テキストで説明 → AIが積算 → 見積書自動生成
```

---

## アーキテクチャ設計

```
painting_ai_system/
├── app.py                      # Streamlitメインアプリ（エントリーポイント）
├── requirements.txt
├── .env.example
│
├── core/                       # ビジネスロジック中枢
│   ├── __init__.py
│   ├── session_manager.py      # 案件セッション管理
│   ├── estimation_engine.py    # 積算エンジン（数量計算）
│   ├── price_calculator.py     # 単価適用・金額計算
│   └── quote_generator.py      # 見積書生成
│
├── modules/                    # AIモジュール（交換可能設計）
│   ├── __init__.py
│   ├── llm_client.py           # LLMクライアント（OpenAI/ローカルLLM対応）
│   ├── image_analyzer.py       # 写真解析モジュール
│   ├── drawing_reader.py       # 図面読取りモジュール（Phase2）
│   ├── speech_processor.py     # 音声認識モジュール（Phase3）
│   └── question_engine.py      # 不足情報質問エンジン
│
├── data/
│   ├── unit_prices/
│   │   └── default_prices.json # 単価表（JSONで管理、変更不要）
│   ├── templates/
│   │   └── quote_template.xlsx # 見積書Excelテンプレート
│   └── past_estimates/         # 過去見積りデータ（学習用）
│
├── utils/
│   ├── __init__.py
│   ├── file_handler.py         # ファイル入出力
│   └── formatters.py           # データ整形ユーティリティ
│
├── output/                     # 生成された見積書の出力先
└── tests/                      # テストコード
```

---

## 技術スタック

| 領域 | 技術 | 理由 |
|------|------|------|
| UI | Streamlit | 現場向けシンプルUI、Python完結 |
| LLM | OpenAI GPT-4o（→将来ローカルLLM移行可） | 画像＋テキスト同時処理、高精度 |
| 画像解析 | GPT-4o Vision API | 外壁・屋根・部位の識別 |
| 見積書出力 | openpyxl（Excel）、reportlab（PDF） | 会社フォーマット対応 |
| データ管理 | JSON（単価表・ルール） | プログラム変更不要で単価更新可 |
| 音声認識 | Whisper API（Phase3） | 高精度日本語対応 |

---

## 開発ロードマップ

### Phase 1（現在）: 写真＋テキストで見積書作成
- [x] フォルダ構成・基盤設計
- [x] 単価表JSON設計
- [x] LLMクライアント（OpenAI）
- [x] 画像解析モジュール
- [x] 積算エンジン
- [x] 不足情報質問エンジン
- [x] Streamlit UI
- [x] Excel/PDF見積書出力

### Phase 2: 図面解析追加
- [ ] PDF/JPEG図面からの寸法・窓・ドア認識
- [ ] 面積自動計算精度向上

### Phase 3: 音声入力対応
- [ ] Whisper APIによるリアルタイム音声認識
- [ ] モバイル対応UI

### Phase 4: 会社独自ルール学習
- [ ] 過去見積りからの単価・利益率学習
- [ ] 施主別・建物種別の傾向分析

### Phase 5: 積算精度向上
- [ ] CAD図面対応
- [ ] ローカルLLM（Gemma等）移行
- [ ] 精度測定・改善サイクル

---

## 起動方法

```bash
# 依存関係インストール
pip install -r requirements.txt

# 環境変数設定
cp .env.example .env
# .envにOPENAI_API_KEYを設定

# アプリ起動
streamlit run app.py
```

---

## AIの積算方針

- 推定値には必ず「📊 推定」マークを表示
- 要確認項目には「⚠️ 要確認」マークを表示  
- すべての数量に根拠を記載
- 断言せず、確認ポイントを明示する
