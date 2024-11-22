            , KIMBALL.UTM_TO_FINANCIAL_CHANNEL(
                                                       UTM_SOURCE
                                                      ,UTM_MEDIUM
                                                      ,UTM_CAMPAIGN
                                                      ,TRY_CAST(UTM_CONTENT AS NUMBER(38,0))
                                                      ,NULL
                                                      ,NULL
                                                      ,'Микрокредиты'
                                                      )
