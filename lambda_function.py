import boto3
import json
import datetime
from dateutil import tz
import os
from concurrent.futures import ThreadPoolExecutor
import logging
import csv
import io

# Set up the logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Create a StreamHandler and set the log level to INFO
handler = logging.StreamHandler()
handler.setLevel(logging.INFO)
    
# Create a Formatter and set it to the handler
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)

# Add the handler to the logger
logger.addHandler(handler)

def get_account_id_from_context(context):
    try:
        invoking_lambda_arn = context.invoked_function_arn
        account_id = invoking_lambda_arn.split(':')[4]
        return account_id
    except Exception as e:
        logger.error(f"Failed to get AWS account ID: {e}")
        return None


def get_amis_in_region(region_name: str):
    try:
        ec2_client = boto3.client('ec2', region_name=region_name)
        response = ec2_client.describe_images(Owners=['self'])
        amis = response['Images']
        for ami in amis:
            ami['Region'] = region_name

        return amis
    except Exception as e:
        logger.error(f"Failed to retrieve AMIs in region {region_name}: {e}")
        return []


def get_snapshots_in_region(region_name: str):
    try:
        ec2_client = boto3.client('ec2', region_name=region_name)
        response = ec2_client.describe_snapshots(OwnerIds=['self'])
        snapshots = response['Snapshots']
        for snapshot in snapshots:
            snapshot['Region'] = region_name
        return snapshots
    except Exception as e:
        logger.error(f"Failed to retrieve snapshots in region {region_name}: {e}")
        return []


def retrieve_amis_snapshots_data():
    try:
        ec2_client = boto3.client('ec2')

        # Get all AWS regions available in the account
        regions = ec2_client.describe_regions()['Regions']

        # Concurrently retrieves AMIs and snapshots data using ThreadPoolExecutor's 'executor.map', which improves data retrieval efficiency.
        with ThreadPoolExecutor() as executor:
            # Retrieves AMI data for each region concurrently.
            amis_data = list(executor.map(get_amis_in_region, [region['RegionName'] for region in regions]))
            # Retrieves Snapshot data for each region concurrently.
            snapshots_data = list(executor.map(get_snapshots_in_region, [region['RegionName'] for region in regions]))

        # Extract all AMIs and snapshots from the retrieved data lists.
        all_amis = [ami for amis in amis_data for ami in amis]
        all_snapshots = [snapshot for snapshots in snapshots_data for snapshot in snapshots]
        return all_amis, all_snapshots
    except Exception as e:
        logger.error(f"Failed to retrieve AMIs and snapshots data: {e}")
        return [], []


def process_data(all_amis,all_snapshots):
    try:

        # Calculate the start date for filtering AMIs and snapshots created within the last 7 days.
        start_date = datetime.datetime.now() - datetime.timedelta(days=7)

        # Initialize lists to store the details of AMIs and snapshots created before 7 days.
        amis_created_before_7_days = []
        snapshots_created_before_7_days = []

        # Variables to keep track of counts and dates.
        total_amis_count = len(all_amis)
        total_snapshots_count = len(all_snapshots)
        total_amis_before_7_days = 0
        total_snapshots_before_7_days = 0
        oldest_ami_date = None
        oldest_snapshot_date = None

        if total_amis_count ==0:
            ami_message = f"AMIs:\nTotal AMIs created within the last 7 days: 0\nTotal AMIs created before the last 7 days: 0\n"
            logger.info("No AMIs found in the account.")
            
        else:
            # Filter AMIs created before 7 days and track oldest AMI date.
            for ami in all_amis:
                creation_date_str = ami.get('CreationDate')
                # if creation_date_str:
                creation_date = datetime.datetime.strptime(creation_date_str, '%Y-%m-%dT%H:%M:%S.%fZ')
                if creation_date < start_date:
                    total_amis_before_7_days += 1
                    amis_created_before_7_days.append({
                        'Name': ami.get('Name', 'N/A'),
                        'ID': ami.get('ImageId', 'N/A'),
                        'Date': creation_date.strftime('%Y-%m-%d'),
                        'Time': creation_date.strftime('%H:%M:%S'),
                        'Region': ami['Region']
                    })
                # Check if this is the oldest AMI date.
                if oldest_ami_date is None or creation_date < oldest_ami_date:
                    oldest_ami_date = creation_date
            oldest_ami_creation_date = oldest_ami_date.strftime('%Y-%m-%d')
            oldest_ami_creation_time = oldest_ami_date.strftime('%H:%M:%S')
            total_amis_last_7_days = total_amis_count - total_amis_before_7_days
            ami_message = f"AMIs:\nTotal AMIs created within the last 7 days: {total_amis_last_7_days}\nTotal AMIs created before the last 7 days: {total_amis_before_7_days}\nOldest AMI Creation Date: {oldest_ami_creation_date} Time: {oldest_ami_creation_time} TimeZone: UTC\n\n"
            
        if all_snapshots:
            for snapshot in all_snapshots:
                creation_date = snapshot['StartTime'].replace(tzinfo=None)
                if creation_date < start_date:
                    total_snapshots_before_7_days += 1
                    snapshots_created_before_7_days.append({
                        'Name': snapshot.get('Name', 'N/A'),
                        'ID': snapshot.get('SnapshotId', 'N/A'),
                        'Date': creation_date.strftime('%Y-%m-%d'),
                        'Time': creation_date.strftime('%H:%M:%S'),
                        'Region': snapshot['Region']
                    })
                # Check if this is the oldest snapshot date.
                if oldest_snapshot_date is None or creation_date < oldest_snapshot_date:
                        oldest_snapshot_date = creation_date
            oldest_snapshot_creation_date = oldest_snapshot_date.strftime('%Y-%m-%d')
            oldest_snapshot_creation_time = oldest_snapshot_date.strftime('%H:%M:%S')
            total_snapshots_last_7_days = total_snapshots_count - total_snapshots_before_7_days
            snapshot_message = f"Snapshots:\nTotal Snapshots created within the last 7 days: {total_snapshots_last_7_days}\nTotal Snapshots created before the last 7 days: {total_snapshots_before_7_days}\nOldest Snapshot Creation Date: {oldest_snapshot_creation_date} Time: {oldest_snapshot_creation_time} TimeZone: UTC\n\n"
        

        # Create a formatted message with details about AMIs and snapshots.
        ami_snapshot_message = f"{ami_message}{snapshot_message}"

        # Log the formatted message containing the details about AMIs and snapshots.
        logger.info(ami_snapshot_message)
        return ami_snapshot_message, amis_created_before_7_days, snapshots_created_before_7_days
    except Exception as e:
        # Log any exceptions that occurred during the data processing.
        logger.error(f"An error occurred during data processing: {e}")
        return None


def upload_csv_to_s3(amis_created_before_7_days, snapshots_created_before_7_days, s3_bucket):
    try:
        # Create a timestamp for a unique file name.
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d__%H-%M-%S")

        # Create a temporary file-like object in memory to store the CSV content.
        csv_buffer = io.StringIO()
        csv_writer = csv.writer(csv_buffer)
        csv_writer.writerow(['Name', 'ID', 'Date', 'Time(UTC)', 'Region'])

        file_name = ""
        # Write AMIs data to the CSV buffer.
        if amis_created_before_7_days:
            csv_buffer.write("\nAMIs\n")
            for ami in amis_created_before_7_days:
                csv_writer.writerow([ami['Name'], ami['ID'], ami['Date'], ami['Time'], ami['Region']])
            file_name = f"AMIs__"
        # Write Snapshots data to the CSV buffer.
        csv_buffer.write("\nSnapshots\n")
        for snapshot in snapshots_created_before_7_days:
            csv_writer.writerow([snapshot['Name'], snapshot['ID'], snapshot['Date'], snapshot['Time'], snapshot['Region']])
        file_name += f"Snapshots__before_7_days__{timestamp}.csv"
        
        # Create an S3 client with the specified region
        s3_client = boto3.client('s3')

        # Specify the S3 key (object key) where the CSV file will be stored in the bucket.
        s3_key = f"Old-AMI-Snapshot/{file_name}"

        # Upload the in-memory buffer to S3 using put_object method.
        s3_client.put_object(Bucket=s3_bucket, Key=s3_key, Body=csv_buffer.getvalue())

        # Log the successful upload of CSV data to S3.
        logger.info(f"CSV data uploaded to S3 bucket: '{s3_bucket}' with key: '{s3_key}'.")
        return file_name
    except Exception as e:
        # Log any exceptions that occurred during CSV data upload to S3.
        logger.error(f"An error occurred while uploading CSV data to S3: {e}")
        return None


def publish_sns_notification(account_name, account_id, ami_snapshot_message, s3_bucket, file_name):
    try:
        sns = boto3.client('sns')
        topic_arn = os.environ.get('TOPIC_ARN')
        
        key = "Old-AMI-Snapshot/" + file_name
        s3 = boto3.client('s3')
        presigned_url = s3.generate_presigned_url('get_object',Params={'Bucket': s3_bucket,'Key': key},ExpiresIn=43200)
        
        # Compose the message to be sent in the SNS notification.
        subject = f"AMIs and Snapshots in the Account Name: {account_name} Account id: {account_id}"
        message = f"Account Name: {account_name}\n" \
                  f"Account ID: {account_id}\n\n" \
                  f"{ami_snapshot_message}\n"
        message += f"CSV got saved in s3 bucket in this full path: s3://{s3_bucket}/Old-AMI-Snapshot/{file_name}\n\n"
        message += f"Presigned url(active for 12 hour only): {presigned_url}"

        # Publish the SNS notification with the message and subject.
        sns.publish(TopicArn=topic_arn, Subject=subject, Message=message)

        # Log the successful publishing of SNS notification.
        logger.info("SNS notification published successfully.")
    except Exception as e:
        # Log any exceptions that occurred during SNS notification publishing.
        logger.error(f"An error occurred while publishing SNS notification: {e}")


def lambda_handler(event, context):
    try:
        logger.info('Lambda function started...')
        account_name = os.environ.get("ACCOUNT_NAME")
        account_id = get_account_id_from_context(context)

        # Retrieve AMIs and snapshots data concurrently
        all_amis, all_snapshots = retrieve_amis_snapshots_data()
        if(len(all_amis) == 0 and len(all_snapshots) == 0):
            logger.info("No AMIs and snapshots found in the account.")
                       
        else:
            # Process the retrieved data to get the required information
            ami_snapshot_message, amis_created_before_7_days, snapshots_created_before_7_days = process_data(all_amis, all_snapshots)
            if len(snapshots_created_before_7_days) == 0:
                logger.info("No AMIs and Snapshots are in the account before 7 days.")
            else:
                # Specify the S3 bucket name where the CSV file will be stored.
                s3_bucket = os.environ.get('BUCKET_NAME')

                # Upload the CSV file to S3
                file_name = upload_csv_to_s3(amis_created_before_7_days, snapshots_created_before_7_days, s3_bucket)

                # Publish SNS notification
                publish_sns_notification(account_name, account_id, ami_snapshot_message, s3_bucket, file_name)


    except Exception as e:
        # Handle any unexpected exceptions in the lambda_handler itself
        logger.error(f"An unexpected error occurred: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps('Function encountered an error!')
        }

    return {
        'statusCode': 200,
        'body': json.dumps('Function execution completed successfully!')
    }
