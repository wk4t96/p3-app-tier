# -*- coding: utf-8 -*-
import os
import json
import boto3
import base64
import subprocess
import time
from pathlib import Path
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv  # 新增

# 讀取 .env 檔
load_dotenv()

# === 設定區 ===
reqQueueUrl = "131567-request-queue"
respQueueUrl = "131567-response-queue"
inputBucketName = "s3-yjche-input"
outputBucketName = "s3-yjche-output"

# === 初始化 AWS 用戶端，改用從 .env 讀取的環境變數，不指定 profile_name ===
session = boto3.Session(
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    region_name = os.getenv("AWS_DEFAULT_REGION", "ap-northeast-2") # 預設區域為 ap-northeast-2
)
sqs = session.client("sqs")
s3 = session.client("s3")

# === 路徑設定 ===
homeDir = os.environ.get("HOME", "/home/ubuntu")
modelDir = os.path.join(homeDir, "model")
appDir = os.path.join(homeDir, "app")
tempDir = os.path.join(appDir, "temp")
Path(tempDir).mkdir(parents=True, exist_ok=True)

# === 處理請求 ===
def getRequestfromWebTier():
    try:
        receive_params = {
            'QueueUrl': reqQueueUrl,
            'MaxNumberOfMessages': 1,
            'WaitTimeSeconds': 19,
        }
        response = sqs.receive_message(**receive_params)

        messages = response.get("Messages", [])
        if messages:
            message = messages[0]
            body = json.loads(message["Body"])
            fileName = body["fileName"]
            imageData = body["imageData"]

            tempFilePath = os.path.join(tempDir, fileName)
            with open(tempFilePath, "wb") as f:
                f.write(base64.b64decode(imageData))

            pythonScriptPath = os.path.join(modelDir, "face_recognition.py")
            try:
                result = subprocess.check_output(["python3", pythonScriptPath, tempFilePath], stderr=subprocess.STDOUT)
                recognitionResult = result.decode("utf-8").strip()
                print(f"Recognition result: {recognitionResult}")
            except subprocess.CalledProcessError as e:
                print(f"exec error: {e.output.decode('utf-8')}")
                return

            resultKey = ".".join(fileName.split(".")[:-1])
            s3.put_object(Bucket=outputBucketName, Key=resultKey, Body=recognitionResult)

            responseMessage = {
                "fileName": resultKey + ".jpg",
                "result": recognitionResult,
            }
            sqs.send_message(
                QueueUrl=respQueueUrl,
                MessageBody=json.dumps(responseMessage)
            )
            print(f"uploaded to S3 as {resultKey}")
            print("Message sent to Resp QUEUE.")

            sqs.delete_message(
                QueueUrl=reqQueueUrl,
                ReceiptHandle=message["ReceiptHandle"]
            )

            os.remove(tempFilePath)
            getRequestfromWebTier()  # 下一輪

        else:
            print("DONEE.")
            time.sleep(15)
            getRequestfromWebTier()

    except Exception as e:
        print("Erroor found:", str(e))
        time.sleep(15)
        getRequestfromWebTier()


# 啟動處理
if __name__ == "__main__":
    getRequestfromWebTier()
