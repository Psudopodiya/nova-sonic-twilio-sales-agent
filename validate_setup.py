#!/usr/bin/env python3
"""
Setup validation script for Nova Sonic Voice AI System.
Checks all prerequisites and provides clear error messages.
"""
import os
import sys
import asyncio
from pathlib import Path
from dotenv import load_dotenv
from loguru import logger

# Load environment variables
load_dotenv(override=True)

# Color codes for terminal output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'


def print_header():
    """Print header"""
    print(f"\n{BLUE}{'='*60}")
    print("Nova Sonic Voice AI - Setup Validation")
    print(f"{'='*60}{RESET}\n")


def check_env_file():
    """Check if .env file exists"""
    print(f"{BLUE}Checking .env file...{RESET}")
    
    if not Path(".env").exists():
        print(f"{RED}✗ .env file not found{RESET}")
        print(f"{YELLOW}  Create one by copying example_env:")
        print(f"  cp example_env .env{RESET}")
        return False
    
    print(f"{GREEN}✓ .env file found{RESET}")
    return True


def check_twilio_credentials():
    """Validate Twilio credentials"""
    print(f"\n{BLUE}Checking Twilio credentials...{RESET}")
    
    errors = []
    warnings = []
    
    # Check required variables
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    phone_number = os.getenv("TWILIO_PHONE_NUMBER")
    
    if not account_sid:
        errors.append("TWILIO_ACCOUNT_SID is missing")
    elif account_sid.startswith("AC") and len(account_sid) == 34:
        print(f"{GREEN}✓ TWILIO_ACCOUNT_SID format looks correct{RESET}")
    else:
        warnings.append("TWILIO_ACCOUNT_SID format may be incorrect (should start with 'AC')")
    
    if not auth_token:
        errors.append("TWILIO_AUTH_TOKEN is missing")
    elif len(auth_token) == 32:
        print(f"{GREEN}✓ TWILIO_AUTH_TOKEN format looks correct{RESET}")
    else:
        warnings.append("TWILIO_AUTH_TOKEN length may be incorrect (should be 32 characters)")
    
    if not phone_number:
        errors.append("TWILIO_PHONE_NUMBER is missing")
    elif phone_number.startswith("+"):
        print(f"{GREEN}✓ TWILIO_PHONE_NUMBER format looks correct{RESET}")
    else:
        warnings.append("TWILIO_PHONE_NUMBER should start with '+' (e.g., +1234567890)")
    
    # Test connection if credentials exist
    if account_sid and auth_token:
        try:
            from twilio.rest import Client
            client = Client(account_sid, auth_token)
            account = client.api.accounts(account_sid).fetch()
            print(f"{GREEN}✓ Twilio connection successful: {account.friendly_name}{RESET}")
        except Exception as e:
            error_msg = str(e)
            if "authentication" in error_msg.lower():
                errors.append("Twilio authentication failed - check your credentials")
            else:
                errors.append(f"Twilio connection failed: {error_msg}")
    
    return errors, warnings


def check_aws_credentials():
    """Validate AWS credentials"""
    print(f"\n{BLUE}Checking AWS credentials...{RESET}")
    
    errors = []
    warnings = []
    
    # Check required variables
    region = os.getenv("AWS_REGION")
    access_key = os.getenv("aws_access_key_id")
    secret_key = os.getenv("aws_secret_access_key")
    session_token = os.getenv("aws_session_token")
    
    if not region:
        errors.append("AWS_REGION is missing")
    elif region == "us-east-1":
        print(f"{GREEN}✓ AWS_REGION set to us-east-1 (correct for Nova Sonic){RESET}")
    else:
        warnings.append(f"AWS_REGION is {region} - Nova Sonic works best in us-east-1")
    
    if not access_key:
        errors.append("aws_access_key_id is missing")
    elif access_key.startswith("AKIA") and len(access_key) == 20:
        print(f"{GREEN}✓ aws_access_key_id format looks correct{RESET}")
    elif access_key.startswith("ASIA") and len(access_key) == 20:
        print(f"{GREEN}✓ aws_access_key_id format looks correct (temporary credentials){RESET}")
        if not session_token:
            warnings.append("aws_session_token may be required for temporary credentials")
    else:
        warnings.append("aws_access_key_id format may be incorrect")
    
    if not secret_key:
        errors.append("aws_secret_access_key is missing")
    elif len(secret_key) == 40:
        print(f"{GREEN}✓ aws_secret_access_key format looks correct{RESET}")
    else:
        warnings.append("aws_secret_access_key length may be incorrect")
    
    # Test AWS connection
    if access_key and secret_key and region:
        try:
            import boto3
            # Create a simple STS client to test credentials
            sts = boto3.client(
                'sts',
                region_name=region,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                aws_session_token=session_token
            )
            identity = sts.get_caller_identity()
            print(f"{GREEN}✓ AWS connection successful: {identity['Arn']}{RESET}")
            
            # Check Bedrock access
            bedrock = boto3.client(
                'bedrock-runtime',
                region_name=region,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                aws_session_token=session_token
            )
            print(f"{GREEN}✓ AWS Bedrock Runtime accessible{RESET}")
            
        except Exception as e:
            error_msg = str(e)
            if "InvalidClientTokenId" in error_msg:
                errors.append("AWS credentials are invalid")
            elif "ExpiredToken" in error_msg:
                errors.append("AWS session token has expired")
            elif "AccessDenied" in error_msg:
                errors.append("AWS account doesn't have Bedrock access")
            else:
                errors.append(f"AWS connection failed: {error_msg}")
    
    return errors, warnings


def check_public_host():
    """Check PUBLIC_HOST configuration"""
    print(f"\n{BLUE}Checking PUBLIC_HOST configuration...{RESET}")
    
    errors = []
    warnings = []
    
    public_host = os.getenv("PUBLIC_HOST")
    
    if not public_host:
        errors.append("PUBLIC_HOST is missing")
    elif public_host == "your.domain.com":
        errors.append("PUBLIC_HOST is still set to default value")
        print(f"{YELLOW}  For local testing, use ngrok:")
        print(f"  1. Run: ngrok http 7860")
        print(f"  2. Copy the URL (e.g., abc123.ngrok-free.app)")
        print(f"  3. Set PUBLIC_HOST=abc123.ngrok-free.app in .env{RESET}")
    elif "ngrok" in public_host:
        print(f"{GREEN}✓ PUBLIC_HOST configured for ngrok: {public_host}{RESET}")
    elif "localhost" in public_host or "127.0.0.1" in public_host:
        warnings.append("PUBLIC_HOST is set to localhost - Twilio won't be able to reach it")
    else:
        print(f"{GREEN}✓ PUBLIC_HOST configured: {public_host}{RESET}")
    
    use_https = os.getenv("USE_HTTPS", "false").lower() == "true"
    if "ngrok" in str(public_host) and not use_https:
        warnings.append("Consider setting USE_HTTPS=true when using ngrok")
    
    return errors, warnings


def check_system_prompt():
    """Check if system_prompt.txt exists"""
    print(f"\n{BLUE}Checking system prompt...{RESET}")
    
    if Path("system_prompt.txt").exists():
        with open("system_prompt.txt", "r") as f:
            content = f.read().strip()
        if content:
            print(f"{GREEN}✓ system_prompt.txt found ({len(content)} characters){RESET}")
        else:
            print(f"{YELLOW}⚠ system_prompt.txt is empty{RESET}")
    else:
        print(f"{YELLOW}⚠ system_prompt.txt not found (will use default){RESET}")
        # Create a default one
        with open("system_prompt.txt", "w") as f:
            f.write("You are a helpful AI assistant.")
        print(f"{GREEN}  Created default system_prompt.txt{RESET}")
    
    return [], []


def check_python_packages():
    """Check if required Python packages are installed"""
    print(f"\n{BLUE}Checking Python packages...{RESET}")
    
    required = {
        "fastapi": "FastAPI web framework",
        "uvicorn": "ASGI server",
        "websockets": "WebSocket support",
        "twilio": "Twilio SDK",
        "boto3": "AWS SDK",
        "loguru": "Logging",
        "python-dotenv": "Environment variables",
        "aiohttp": "Async HTTP",
        "numpy": "Numerical processing"
    }
    
    missing = []
    for package, description in required.items():
        try:
            __import__(package.replace("-", "_"))
            print(f"{GREEN}✓ {package} installed{RESET}")
        except ImportError:
            missing.append(f"{package} ({description})")
    
    if missing:
        return [f"Missing Python packages: {', '.join(missing)}"], []
    
    return [], []


def main():
    """Run all validation checks"""
    print_header()
    
    all_errors = []
    all_warnings = []
    
    # Check .env file
    if not check_env_file():
        print(f"\n{RED}Cannot proceed without .env file{RESET}")
        sys.exit(1)
    
    # Check all components
    checks = [
        ("Twilio", check_twilio_credentials),
        ("AWS", check_aws_credentials),
        ("Network", check_public_host),
        ("System Prompt", check_system_prompt),
        ("Python Packages", check_python_packages)
    ]
    
    for name, check_func in checks:
        errors, warnings = check_func()
        all_errors.extend(errors)
        all_warnings.extend(warnings)
    
    # Print summary
    print(f"\n{BLUE}{'='*60}")
    print("Validation Summary")
    print(f"{'='*60}{RESET}")
    
    if all_errors:
        print(f"\n{RED}Errors found ({len(all_errors)}):{RESET}")
        for i, error in enumerate(all_errors, 1):
            print(f"{RED}  {i}. {error}{RESET}")
    
    if all_warnings:
        print(f"\n{YELLOW}Warnings ({len(all_warnings)}):{RESET}")
        for i, warning in enumerate(all_warnings, 1):
            print(f"{YELLOW}  {i}. {warning}{RESET}")
    
    if not all_errors:
        print(f"\n{GREEN}✅ All checks passed! System is ready to start.{RESET}")
        print(f"\n{BLUE}To start the server, run:{RESET}")
        print(f"  python server.py")
        return 0
    else:
        print(f"\n{RED}❌ Please fix the errors above before starting the server.{RESET}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
