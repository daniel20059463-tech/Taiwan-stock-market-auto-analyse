# Dashboard 四窗格覆蓋實作計畫

1. 重寫 `src/components/Dashboard.tsx`
   - 保留資料來源與圖表初始化
   - 重新組裝為四窗格布局
   - 修正亂碼文案

2. 重寫 `src/components/AppShell.tsx`
   - 清理側欄文案
   - 保持既有路由與入口按鈕

3. 更新測試
   - `src/components/Dashboard.test.tsx`
   - `src/components/AppShell.test.tsx`

4. 驗證
   - `npm.cmd test -- src/components/AppShell.test.tsx src/components/Dashboard.test.tsx`
   - `npm.cmd test`
   - `npm.cmd run build`
