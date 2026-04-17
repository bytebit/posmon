import argparse
import os
import requests
import json
import smtplib
from email.mime.text import MIMEText
from typing import List, Dict, Any
from dotenv import load_dotenv

COINGECKO_API_URL = "https://api.coingecko.com/api/v3/coins/markets"


def get_market_data() -> List[Dict[str, Any]]:
    params = {
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": 250,
        "page": 1,
        "sparkline": False,
        "price_change_percentage": "24h"
    }

    try:
        response = requests.get(COINGECKO_API_URL, params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching market data: {e}")
        return []


def calculate_volatility(coin: Dict[str, Any]) -> float:
    price_change_24h = coin.get("price_change_percentage_24h", 0)
    if price_change_24h is None:
        return 0.0
    return abs(price_change_24h)


def get_top_volatility_coins(data: List[Dict[str, Any]], top_n: int = 10) -> List[Dict[str, Any]]:
    for coin in data:
        coin["volatility"] = calculate_volatility(coin)

    sorted_coins = sorted(data, key=lambda x: x["volatility"], reverse=True)
    return sorted_coins[:top_n]


def format_output(coins: List[Dict[str, Any]]) -> str:
    output = "\n过去24小时内波动最大的加密货币 Top 10\n"
    output += "-" * 80 + "\n"
    output += f"{'Rank':<5} {'Name':<20} {'Symbol':<10} {'Price (USD)':<15} {'24h Change':<15} {'Volatility':<10}\n"
    output += "-" * 80 + "\n"

    for i, coin in enumerate(coins, 1):
        name = coin.get("name", "N/A")
        symbol = coin.get("symbol", "N/A").upper()
        price = coin.get("current_price", 0)
        price_change = coin.get("price_change_percentage_24h", 0)
        volatility = coin.get("volatility", 0)

        price_str = f"${price:.4f}"
        change_str = f"{price_change:+.2f}%"
        volatility_str = f"{volatility:.2f}%"

        output += f"{i:<5} {name:<20} {symbol:<10} {price_str:<15} {change_str:<15} {volatility_str:<10}\n"

    output += "-" * 80 + "\n"
    return output


def send_email(subject: str, body: str, smtp_host: str, smtp_port: int, smtp_user: str, smtp_pass: str,
               email_from: str, email_to: str, use_tls: bool = True, use_ssl: bool = False) -> None:
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = email_from
    recipients = [x.strip() for x in email_to.split(",") if x.strip()]
    msg["To"] = ", ".join(recipients)

    # 增加超时时间到60秒
    timeout = 60
    
    if use_ssl:
        server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=timeout)
    else:
        server = smtplib.SMTP(smtp_host, smtp_port, timeout=timeout)
        if use_tls:
            server.starttls()

    try:
        # 打印连接信息用于调试
        print(f"Connecting to {smtp_host}:{smtp_port} with SSL={use_ssl}, TLS={use_tls}")
        
        if smtp_user and smtp_pass:
            print(f"Logging in as {smtp_user}")
            server.login(smtp_user, smtp_pass)
            print("Login successful")
        
        server.send_message(msg, from_addr=email_from, to_addrs=recipients)
        print("Message sent successfully")
    finally:
        server.quit()


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="获取过去24小时内波动最大的加密货币Top 10")
    parser.add_argument("--email", action="store_true", help="发送邮件通知")
    parser.add_argument("--smtp-host", default=os.getenv("SMTP_HOST", ""), help="SMTP服务器地址")
    parser.add_argument("--smtp-port", type=int, default=int(os.getenv("SMTP_PORT", "587")), help="SMTP端口")
    parser.add_argument("--smtp-user", default=os.getenv("SMTP_USER", ""), help="SMTP用户名")
    parser.add_argument("--smtp-pass", default=os.getenv("SMTP_PASS", ""), help="SMTP密码")
    parser.add_argument("--email-from", default=os.getenv("EMAIL_FROM", ""), help="发件人邮箱")
    parser.add_argument("--email-to", default=os.getenv("EMAIL_TO", ""), help="收件人邮箱（逗号分隔）")
    # 从环境变量读取默认值
    default_use_tls = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
    default_use_ssl = os.getenv("SMTP_USE_SSL", "false").lower() == "true"
    
    parser.add_argument("--use-tls", type=lambda x: x.lower() == "true", default=default_use_tls, help="是否使用TLS")
    parser.add_argument("--use-ssl", type=lambda x: x.lower() == "true", default=default_use_ssl, help="是否使用SSL")
    args = parser.parse_args()

    print("Fetching market data from CoinGecko API...")
    market_data = get_market_data()

    if not market_data:
        print("Failed to fetch market data. Exiting.")
        return

    print(f"Fetched data for {len(market_data)} cryptocurrencies.")
    print("Calculating volatility...")

    top_volatility_coins = get_top_volatility_coins(market_data)
    output = format_output(top_volatility_coins)
    print(output)

    with open("volatility_top10.json", "w", encoding="utf-8") as f:
        json.dump(top_volatility_coins, f, ensure_ascii=False, indent=2)
    print("Results saved to volatility_top10.json")

    if args.email:
        if not all([args.smtp_host, args.email_from, args.email_to]):
            print("Error: SMTP configuration is incomplete. Email not sent.")
            return

        try:
            print(f"Sending email to {args.email_to}...")
            send_email(
                subject="[加密货币波动警报] 过去24小时波动最大的Top 10",
                body=output,
                smtp_host=args.smtp_host,
                smtp_port=args.smtp_port,
                smtp_user=args.smtp_user,
                smtp_pass=args.smtp_pass,
                email_from=args.email_from,
                email_to=args.email_to,
                use_tls=args.use_tls,
                use_ssl=args.use_ssl
            )
            print("Email sent successfully!")
        except Exception as e:
            print(f"Failed to send email: {e}")


if __name__ == "__main__":
    main()
