@echo off
echo === ZamPOS API Quick Test ===
echo.

echo [1] Health Check...
curl http://127.0.0.1:8000/health
echo.

echo [2] Get BTC/ZMW Rate...
curl http://127.0.0.1:8000/price/rate
echo.

echo [3] Convert 100 ZMW to sats...
curl http://127.0.0.1:8000/price/convert?zmw=100
echo.

echo [4] Get Merchant #1 (serah salon)...
curl http://127.0.0.1:8000/merchant/1
echo.

echo [5] Get Merchant Transactions...
curl http://127.0.0.1:8000/merchant/1/transactions
echo.

echo === Done ===
pause