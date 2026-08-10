# 3Dポーズ編集基盤 引き継ぎ（B実機確認済み）

更新日: 2026-08-11  
作業元: B PC（VSeeFace実機あり）  
次回作業: A PC（Codex・コード/UI開発可能、VSeeFace実機確認不可）

## 1. 結論

現在の `tools/3d_pose_editor/` は、正式な共通ポーズ編集基盤としては使わない。

- VSeeFaceへ送るHTTP/VMC経路、JSON保存・読込の考え方は再利用できる。
- 画面の簡易マネキン、手の疑似表示、現在の軸設定は実VRMと一致しない。
- 正式版は、BのVSeeFaceで使っているものと同一のVRMを画面へ読み込み、実際のHumanoidボーンを直接回す構造にする。
- 判定は「C」。送信部分は残せるが、編集・表示部分は実VRM方式へ置き換える必要がある。

## 2. Bで確認した実機固有情報

### VSeeFaceで実際に読み込まれているVRM

VSeeFace設定:

`C:\Users\dende\AppData\LocalLow\Emiliana_vt\VSeeFace\settings.ini`

設定値:

`AvatarFile=C:\Users\dende\Desktop\AvatarSample_B.vrm`

実ファイル:

`C:\Users\dende\Desktop\AvatarSample_B.vrm`

- サイズ: `14681744` bytes
- SHA-256: `7CDD3E660F9396A6AD82DA319D301A541493034504780882B58AACFC868ACD18`

ワークスペース内で同一ハッシュのファイル:

`avatars/AvatarSample_B_clean_hands_v3.vrm`

したがって、Aで実VRMエディタを作る際の基準モデルは
`avatars/AvatarSample_B_clean_hands_v3.vrm` とする。

### VSeeFaceのVMC受信

現在確認できた設定:

- `VMCReceiveEnable=1`
- `VMCReceiveMix=0`
- `VMCReceiveApplyExpressions=0`
- `VMCReceiveTrackFaceFeatures=1`
- `VMCReceiveTrackBlendshapes=1`
- `TrackLeapMotion=0`
- `Mirror=0`

送信先は `vsf_controller.py` の以下の値:

- VMC/UDP: `127.0.0.1:39539`
- HTTP操作API: `127.0.0.1:8766`

### B実機で確認済みの事実

- CodexからRightUpperArmへ回転を送ると、VSeeFace実キャラの右腕が動く。
- 旧3D画面のRightUpperArmテストボタンからも、HTTP API → `vsf_controller.py` → VMC → VSeeFaceの経路で動作した。
- RightUpperArm Zは、管理側ZからVSeeFace Zへ同方向で動いた。
- RightUpperArm X/Yは管理画面とVSeeFaceで同じ見え方ではなく、完全な対応は未確定。
- 保存JSONの肩・上腕・前腕・手・親指は `/fortune_pose_adjust` から送信できる。
- `vsf_controller.py` 自体はHumanBodyBones一式（左右の指、腕、脚を含む）をVMC送信できる。
- VSeeFace実画面は `tools/capture_vseeface.ps1` で取得できる。Default desktopを開き、`EnumDesktopWindows` と `PrintWindow` を使用する。

## 3. 現在の接続構造

```text
3D画面（tools/3d_pose_editor/index.html）
  ↓ HTTP POST（一部テスト操作のみ）
http://127.0.0.1:8766/fortune_pose_adjust
  ↓
vsf_controller.py
  ↓ VMC / OSC Bone Transform
127.0.0.1:39539
  ↓
VSeeFace
  ↓
AvatarSample_B.vrm
```

鑑定中の既存フロー:

```text
comment_server.py
  start_fortune_thinking_motion()
  ↓ action=fortune_think
vsf_controller.py
  get_fortune_think_overrides()
  ↓
VSeeFace
  ↓ 鑑定結果準備完了
fortune_think_stop → 通常姿勢 → 結果発話
```

この自動フローはBで、考える動作・AivisSpeech発話・通常姿勢復帰まで1回確認済み。

## 4. 旧3Dツールの現状と問題

主要ファイル:

- `tools/3d_pose_editor/index.html`: Canvasで描く簡易マネキンと編集UI
- `tools/3d_pose_editor/config.json`: 対象ボーン、表示・出力変換、旧thinkingプリセット
- `tools/3d_pose_editor/README.md`: 簡単な説明

問題点:

1. 実VRMを表示していない。
2. 腕は線・円柱、手は独自の箱、指は固定形状で描いている。
3. 人差し指・中指・薬指・小指は `config.json` の編集対象に存在しない。
4. 画面上の4本指は実ボーン角度ではなく、固定座標から生成した疑似表示。
5. 親指表示も `thumbDisplayPoint()` による独自補正で、実モデルの親指位置ではない。
6. `config.json` の既定軸変換は全骨 `axisMap=[X,Y,Z]`、`sign=[1,1,1]` で、実機対応を表していない。
7. 通常のスライダー操作は画面とJSONを更新するだけで、VSeeFaceへ常時送らない。
8. 現在の直接テスト処理はコード上RightUpperArmだけに制限されている。
9. 手の甲・手のひら・親指側・小指側の表示ボタンはあるが、実VRMの面を見ているわけではない。
10. このため、旧画面で自然に見えてもVSeeFaceでは手首や指が大きく崩れる。

## 5. 再利用できる部分

- `/fortune_pose_adjust` のHTTP/CORS経路
- `vsf_controller.py` のVMC送信処理
- HumanBodyBones一式を送る仕組み
- `fortune_think_pose.json` の外部ファイル読込
- JSON保存・読込という運用
- ポーズのプレビュー開始・解除
- 鑑定開始・完了に連動する `fortune_think` / `fortune_think_stop`
- `capture_vseeface.ps1` によるB実機の画像確認

ただし、`/fortune_pose_adjust` の受信許可ボーンは現在
`fortune_think_pose.json` に含まれる肩・上腕・前腕・手・親指だけ。
正式版では全Humanoidボーンを安全に受け取れるよう拡張が必要。

## 6. 考えるポーズの現在地点

`fortune_think_pose.json` の現在値:

```json
{
  "RightShoulder": [-1.58, -2.96, -1.58],
  "RightUpperArm": [-45.97, -26.46, -33.0],
  "RightLowerArm": [49.89, 7.6, -179.57],
  "RightHand": [11.32, 53.97, -11.95],
  "RightThumbProximal": [0.0, -50.0, 100.0],
  "RightThumbIntermediate": [0.0, 0.0, 80.0],
  "RightThumbDistal": [0.0, 0.0, 70.0]
}
```

状態:

- 右肩から顎付近までの腕の構図は改善済み。
- 手の表裏を反転する方向は見つかった。
- 4本指を正面から隠すことはできた。
- 親指は短く横へ畳めた。
- ただし最新画像では拳本体が袖に隠れ、単純なグーとしてまだ読みにくい。
- 完成扱いにしない。
- 旧簡易ツールでこれ以上微調整しない。実VRMエディタで再確認する。

参考画像:

- `fortune_think_bc_attempt3.png`: 腕と拳位置を顎下へ寄せた段階
- `fortune_think_flip_frontback_once.png`: 手の表裏反転方向を確認した画像
- `fortune_think_flipped_fist_attempt2.png`: 4本指が隠れ、親指が長く残った画像
- `fortune_think_thumb_only_attempt.png`: 最新。親指は短くなったが拳本体が袖に隠れ気味

注意:

- 現在起動中の `vsf_controller.py` は起動時点の `FORTUNE_POSE_BASE` を保持する。
- `/fortune_pose_adjust` のpreview値は最新JSONと一致していても、通常の `fortune_think` は再起動するまで古いbaseを使う場合がある。
- 次回Bで本番確認する直前に、controllerだけ再起動してJSONを読み直すこと。

## 7. 今日Bで行った主な作業

- 旧3D画面の正面左右表示を本人基準へ修正。
- RightUpperArmの実ボタン送信、初期値復帰、X/Y/Z選択連動を確認。
- VSeeFace画面取得をDefault desktop + PrintWindow方式へ修正・確認。
- `fortune_think_pose.json` の読込とVSeeFace適用を確認。
- 鑑定開始から考える動作、結果準備後の復帰、AivisSpeech発話まで実フローを確認。
- 考えるポーズの右腕位置と右手方向を実画像で調整。
- 旧3Dツールが正式基盤として不十分であることをコードと実機の両方で確認。
- BのVSeeFaceが実際に使用するVRMと、ワークスペース内v3モデルが同一ハッシュであることを確認。

## 8. 明日Aで最初にやること

大規模実装へ入る前に、次の順で設計と最小プロトタイプを作る。

1. `avatars/AvatarSample_B_clean_hands_v3.vrm` を唯一の基準モデルとして読み込む。
2. Three.js + `@pixiv/three-vrm` 等で、実VRMメッシュとHumanoidボーンを表示する。
3. 旧Canvasマネキンの描画ロジックは流用しない。
4. RightShoulder / RightUpperArm / RightLowerArm / RightHandと、右手15指ボーンを選択できるUIを先に作る。
5. ボーン回転は実VRMのrest/local quaternionを基準に保持し、表示用と送信用で同じ値を使う。
6. 正面・背面・手の甲・手のひら・親指側・小指側は、疑似図ではなく実モデルのカメラを切り替えて確認する。
7. JSONにはEuler値だけでなく、モデル識別子・ボーン名・rest基準・回転順序・バージョンを持たせる設計を検討する。
8. 送信部分はアダプターとして分離し、Aではモック応答でUIを開発する。
9. `/fortune_pose_adjust` は全Humanoidボーンを明示的なallowlistで受け取れるようにする案を作る。
10. Aでは見た目とJSONの一致、保存・再読込、左右、指ボーン階層まで確認する。

最初の完成範囲は右腕・右手だけでよい。足や全身UIを同時に作らない。

## 9. Aだけで進められる作業

- 実VRMの読み込みと描画
- OrbitControls、正面/背面/手アップ等のカメラUI
- Humanoidボーン一覧と選択UI
- ボーンギズモ、ローカル回転、数値入力
- 親指・人差し指・中指・薬指・小指の全関節編集
- Undo/Redo、初期値復帰
- ポーズJSONの保存・読込・バージョン管理
- 既存ポーズを読み込む変換レイヤー
- APIモックと送信payload表示
- 同一VRMを再読込したときの再現性テスト
- 左右表示と本人基準のテスト

## 10. Aでは確認できず、次回Bで確認すること

実VRMエディタの最小版ができてからBで一度だけまとめて確認する。

1. A画面の正面表示とVSeeFaceの本人左右が一致するか。
2. 実VRM画面のlocal rotationをそのままVMCへ送ったとき、各骨が同じ方向へ動くか。
3. RightHandの手の甲・手のひら・親指側・小指側がVSeeFaceと一致するか。
4. 右手15指ボーンが各関節までVSeeFaceへ反映されるか。
5. JSON保存→再読込→VSeeFace送信で同じ姿勢が再現されるか。
6. VSeeFace側のトラッキングがVMCボーンを上書きしないか。
7. 考えるポーズ、手を振る、ピース、指差しのうち、まず1ポーズだけ往復確認する。

## 11. やってはいけない遠回り

- 旧簡易マネキンの見た目を実VRMへ近づける調整を続けない。
- 骨ごとにCodexが角度を推測し続けない。
- AでVSeeFaceの見た目を推測して完成扱いにしない。
- 最初から全身・全ポーズ・アニメーションタイムラインを同時実装しない。
- 手の甲・手のひらを色付き疑似面だけで判断しない。
- 4本指をcontroller内の固定値だけで作り続けない。
- 旧 `config.json` のidentity軸設定を正しい前提にしない。
- Bで軸テストを何十回も繰り返さない。Aで実VRMを基準に作り、Bでは差分検証だけ行う。
- 音声、OBS、TikTok配信、鑑定ロジックへ脱線しない。

## 12. 主要ファイルと役割

- `avatars/AvatarSample_B_clean_hands_v3.vrm`: 正式エディタの基準にする実VRM
- `tools/3d_pose_editor/index.html`: 旧簡易エディタ。UI/APIの参考に限定
- `tools/3d_pose_editor/config.json`: 旧対象骨・旧プリセット・未校正軸設定
- `fortune_think_pose.json`: 現在の考えるポーズ外部値。未完成扱い
- `vsf_controller.py`: HTTP操作、VMCボーン送信、ポーズ動作、固定指カール
- `comment_server.py`: 鑑定フローから `fortune_think` / stopを呼ぶ
- `tools/capture_vseeface.ps1`: BのVSeeFace実画面取得
- `vsf_state.json`: controllerの状態連携
- `comment_server_events.log`: 実フローの確認ログ

## 13. 明日のA Codexへ渡す開始文

```text
C:\Users\dende\Desktop\live_fortune\3D_POSE_DEVELOPMENT_HANDOFF.md を最初から最後まで読んでください。
明日はA PCなのでVSeeFace実機確認はできません。
avatars/AvatarSample_B_clean_hands_v3.vrm を使い、旧Canvasマネキンを拡張せず、同じ実VRMを表示する右腕・右手用エディタの設計と最小プロトタイプから始めてください。
送信APIとJSON資産は再利用し、実機依存の判断は次回B確認項目として分離してください。
音声・OBS・配信・鑑定ロジックには触らないでください。
```
