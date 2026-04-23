# test_breez.py
import asyncio
import breez_sdk_spark as breez

print("Available attributes in breez_sdk_spark:")
print([attr for attr in dir(breez) if not attr.startswith('_')])