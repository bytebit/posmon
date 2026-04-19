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
    """
    从CoinGecko API获取市场数据
    """
    params = {
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": 250,  # 获取足够多的币种以确保有足够的数据计算波动率
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
    """
    计算加密货币的24小时波动率
    使用价格变化百分比的绝对值作为波动率的度量
    """
    price_change_24h = coin.get("price_change_percentage_24h", 0)
    if price_change_24h is None:
        return 0.0
    return abs(price_change_24h)


def get_top_volatility_coins(data: List[Dict[str, Any]], top_n: int = 10) -> List[Dict[str, Any]]:
    """
    获取波动率最大的前N个加密货币
    """
    # 计算每个币种的波动率
    for coin in data:
        coin["volatility"] = calculate_volatility(coin)
    
    # 按波动率排序
    sorted_coins = sorted(data, key=lambda x: x["volatility"], reverse=True)
    
    # 返回前N个
    return sorted_coins[:top_n]


def format_output(coins: List[Dict[str, Any]]) -> str:
    """
    格式化输出结果
    """
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
        
        # 格式化价格和百分比
        price_str = f"${price:.4f}"
        change_str = f"{price_change:+.2f}%"
        volatility_str = f"{volatility:.2f}%"
        
        output += f"{i:<5} {name:<20} {symbol:<10} {price_str:<15} {change_str:<15} {volatility_str:<10}\n"
    
    output += "-" * 80 + "\n"
    return output


def send_email(
    subject: str,
    body: str,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_pass: str,
    email_from: str,
    email_to: str,
    use_tls: bool = True,
    use_ssl: bool = False
) -> None:
    """
    发送邮件
    """
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = email_to
    
    # 连接SMTP服务器
    if use_ssl:
        server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=60)
    else:
        server = smtplib.SMTP(smtp_host, smtp_port, timeout=60)
    
    try:
        if use_tls and not use_ssl:
            server.starttls()
        
        # 登录SMTP服务器
        if smtp_user and smtp_pass:
            server.login(smtp_user, smtp_pass)
        
        # 发送邮件
        server.send_message(msg)
    finally:
        server.quit()


def main():
    """
    主函数
    """
    load_dotenv()
    
    parser = argparse.ArgumentParser(description="获取过去24小时内波动最大的加密货币Top 10")
    parser.add_argument("--email", action="store_true", help="是否发送邮件")
    parser.add_argument("--smtp-host", default=os.getenv("SMTP_HOST"), help="SMTP服务器地址")
    parser.add_argument("--smtp-port", type=int, default=os.getenv("SMTP_PORT", "587"), help="SMTP端口")
    parser.add_argument("--smtp-user", default=os.getenv("SMTP_USER"), help="SMTP用户名")
    parser.add_argument("--smtp-pass", default=os.getenv("SMTP_PASS"), help="SMTP密码")
    parser.add_argument("--email-from", default=os.getenv("EMAIL_FROM"), help="发件人邮箱")
    parser.add_argument("--email-to", default=os.getenv("EMAIL_TO"), help="收件人邮箱")
    parser.add_argument("--use-tls", type=lambda x: x.lower() == "true", default=os.getenv("SMTP_USE_TLS", "true").lower() == "true", help="是否使用TLS")
    parser.add_argument("--use-ssl", type=lambda x: x.lower() == "true", default=os.getenv("SMTP_USE_SSL", "false").lower() == "true", help="是否使用SSL")
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
    
    # 保存结果到文件
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
