# 中古スマホ監視bot 1週間運用ログ

## 1週間の目的
- [ ] 通知品質を安定させる（ノイズ通知を減らす）
- [ ] `review_status` を毎日更新して、判断精度を上げる
- [ ] 週末に summary を見て次週の閾値調整方針を決める

## 運用ルール
- [ ] 1日3回（朝 9:00 / 昼 14:00 / 夜 21:00）を基本に確認する
- [ ] 通知が来なくても「通知0件」として記録する
- [ ] 通知案件は必ず `good / bad / watched / bought` のいずれかに更新する
- [ ] 不明点は「気づきメモ」に残し、週末にまとめて見直す

## 毎日使うコマンド
```bash
python -m app.main --config config.yaml --env .env --verbose run-once
python -m app.main --config config.yaml --env .env review-status list --limit 30 --format tsv
python -m app.main --config config.yaml --env .env review-status set --source mercari_public --item-url "<URL>" --status good
python -m app.main --config config.yaml --env .env review-status summary --timeseries both --format tsv
```

---

## Day1（      /      ）
- [ ] 朝の実行を確認
- [ ] 昼の実行を確認
- [ ] 夜の実行を確認
- [ ] 通知件数を記録（通知なしでも記録）
- [ ] review_status を更新

通知記録（通知0件なら「0件」と記入）:
- 件数: 1
- URL / 価格 / 想定粗利 / 理由:
  - https://jp.mercari.com/item/m32182940750
  - 価格: 33,000円
  - 想定粗利: 22,050円
  - 理由: iPhone 13 128GB / SIMフリー / バッテリー87% / 通知条件クリア

review_status 記録:
- good:
  - m32182940750
  - 理由: auで利用制限、SIMフリー、バッテリー87%、価格が安い
- bad:
- watched:
- bought:

気づきメモ:
- network_restriction_unknown でも、IMEI確認で au なら good 候補あり
- 粗利は少し強気に見積もられている可能性あり


• ## Day2（      /      ）
  - [ ] 朝の実行を確認                                                                            
  - [ ] 昼の実行を確認                                                                            
  - [ ] 夜の実行を確認                                                                            
  - [ ] 通知件数を記録（通知なしでも記録）                                                        
  - [ ] review_status を更新                                                                      

  通知記録（通知0件なら「0件」と記入）:                                                           
  - 件数:                                                                                         
  - URL / 価格 / 想定粗利 / 理由:                                                                 
    -                                                                                             
    - 価格:                                                                                       
    - 想定粗利:                                                                                   
    - 理由:                                                                                       
                                                                                                  
  review_status 記録:                                                                             
  - good:                                                                                         
    -                                                                                             
    - 理由:                                                                                       
  - bad:                                                                                          
    -                                                                                             
    - 理由:                                                                                       
  - watched:                                                                                      
    -                                                                                             
    - 理由:                                                                                       
  - bought:                                                                                       
    -                                                                                             
    - 理由:                                                                                       
                                                                                                  
  気づきメモ:                                                                                     
  -                                                                                               
  -                                                                                               
                                                                                                  
                                                                                                  
  ## Day3（      /      ）                                                                        
  - [ ] 朝の実行を確認                                                                            
  - [ ] 昼の実行を確認                                                                            
  - [ ] 夜の実行を確認                                                                            
  - [ ] 通知件数を記録（通知なしでも記録）                                                        
  - [ ] review_status を更新                                                                      
                                                                                                  
  通知記録（通知0件なら「0件」と記入）:                                                           
  - 件数:                                                                                         
  - URL / 価格 / 想定粗利 / 理由:                                                                 
    -                                                                                             
    - 価格:                                                                                       
    - 想定粗利:                                                                                   
    - 理由:                                                                                       
                                                                                                  
  review_status 記録:                                                                             
  - good:                                                                                         
    -                                                                                             
    - 理由:                                                                                       
  - bad:                                                                                          
    -                                                                                             
    - 理由:                                                                                       
  - watched:                                                                                      
    -                                                                                             
    - 理由:                                                                                       
  - bought:                                                                                       
    -                                                                                             
    - 理由:                                                                                       
                                                                                                  
  気づきメモ:                                                                                     
  -                                                                                               
  -                                                                                               
                                                                                                  
                                                                                                  
  ## Day4（      /      ）                                                                        
  - [ ] 朝の実行を確認                                                                            
  - [ ] 昼の実行を確認                                                                            
  - [ ] 夜の実行を確認                                                                            
  - [ ] 通知件数を記録（通知なしでも記録）                                                        
  - [ ] review_status を更新                                                                      
                                                                                                  
  通知記録（通知0件なら「0件」と記入）:                                                           
  - 件数:
  - URL / 価格 / 想定粗利 / 理由:                                                                 
    -                                                                                             
    - 価格:                                                                                       
    - 想定粗利:                                                                                   
    - 理由:                                                                                       
                                                                                                  
  review_status 記録:                                                                             
  - good:                                                                                         
    -                                                                                             
    - 理由:                                                                                       
  - bad:                                                                                          
    -                                                                                             
    - 理由:                                                                                       
  - watched:                                                                                      
    -                                                                                             
    - 理由:                                                                                       
  - bought:                                                                                       
    -                                                                                             
    - 理由:                                                                                       
                                                                                                  
  気づきメモ:                                                                                     
  -                                                                                               
  -                                                                                               
                                                                                                  
                                                                                                  
  ## Day5（      /      ）                                                                        
  - [ ] 朝の実行を確認                                                                            
  - [ ] 昼の実行を確認                                                                            
  - [ ] 夜の実行を確認                                                                            
  - [ ] 通知件数を記録（通知なしでも記録）                                                        
  - [ ] review_status を更新                                                                      
                                                                                                  
  通知記録（通知0件なら「0件」と記入）:                                                           
  - 件数:                                                                                         
  - URL / 価格 / 想定粗利 / 理由:                                                                 
    -                                                                                             
    - 価格:                                                                                       
    - 想定粗利:                                                                                   
    - 理由:                                                                                       
                                                                                                  
  review_status 記録:                                                                             
  - good:                                                                                         
    -                                                                                             
    - 理由:                                                                                       
  - bad:                                                                                          
    -                                                                                             
    - 理由:                                                                                       
  - watched:
    -                                                                                             
    - 理由:                                                                                       
  - bought:                                                                                       
    -                                                                                             
    - 理由:                                                                                       
                                                                                                  
  気づきメモ:                                                                                     
  -                                                                                               
  -                                                                                               
                                                                                                  
                                                                                                  
  ## Day6（      /      ）                                                                        
  - [ ] 朝の実行を確認                                                                            
  - [ ] 昼の実行を確認                                                                            
  - [ ] 夜の実行を確認                                                                            
  - [ ] 通知件数を記録（通知なしでも記録）                                                        
  - [ ] review_status を更新                                                                      
                                                                                                  
  通知記録（通知0件なら「0件」と記入）:                                                           
  - 件数:
  - URL / 価格 / 想定粗利 / 理由:                                                                 
    -                                                                                             
    - 価格:                                                                                       
    - 想定粗利:                                                                                   
    - 理由:                                                                                       
                                                                                                  
  review_status 記録:                                                                             
  - good:                                                                                         
    -                                                                                             
    - 理由:                                                                                       
  - bad:                                                                                          
    -                                                                                             
    - 理由:                                                                                       
  - watched:                                                                                      
    -                                                                                             
    - 理由:                                                                                       
  - bought:                                                                                       
    -                                                                                             
    - 理由:                                                                                       
                                                                                                  
  気づきメモ:                                                                                     
  -                                                                                               
  -                                                                                               
                                                                                                  
                                                                                                  
  ## Day7（      /      ）                                                                        
  - [ ] 朝の実行を確認                                                                            
  - [ ] 昼の実行を確認                                                                            
  - [ ] 夜の実行を確認                                                                            
  - [ ] 通知件数を記録（通知なしでも記録）                                                        
  - [ ] review_status を更新                                                                      
  - [ ] 週末summaryを確認                                                                         
                                                                                                  
  通知記録（通知0件なら「0件」と記入）:                                                           
  - 件数:                                                                                         
  - URL / 価格 / 想定粗利 / 理由:                                                                 
    -                                                                                             
    - 価格:                                                                                       
    - 想定粗利:                                                                                   
    - 理由:                                                                                       
                                                                                                  
  review_status 記録:                                                                             
  - good:                                                                                         
    -                                                                                             
    - 理由:                                                                                       
  - bad:                                                                                          
    -                                                                                             
    - 理由:                                                                                       
  - watched:                                                                                      
    -                                                                                             
    - 理由:                                                                                       
  - bought:                                                                                       
    -                                                                                             
    - 理由:                                                                                       
                                                                                                  
  気づきメモ:                                                                                     
  -                                                                                               
  -                                                                                               
 
