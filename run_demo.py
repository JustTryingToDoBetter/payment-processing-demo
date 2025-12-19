#!/usr/bin/env python3
"""
Payment Processing Demo Runner

This script demonstrates the complete payment flow by running
each component's demo in sequence.

Usage:
    python run_demo.py          # Run all demos
    python run_demo.py tokenize # Run tokenization demo only
    python run_demo.py bank     # Run bank simulation demo
    python run_demo.py server   # Start the API server
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))


def print_header(title):
    """Print a nice header."""
    print("\n")
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)


def run_all_demos():
    """Run all component demos."""
    
    print_header("💳 PAYMENT PROCESSING SYSTEM DEMO")
    print("""
    This demo walks through the complete payment processing flow.
    Each component will demonstrate its functionality.
    
    Press Enter to continue through each demo...
    """)
    
    demos = [
        ("1. Tokenization (Card → Token)", demo_tokenization),
        ("2. Authorization (Token → Charge)", demo_authorization),
        ("3. Fraud Detection", demo_fraud_detection),
        ("4. Webhook System", demo_webhooks),
        ("5. Issuing Bank Simulation", demo_issuing_bank),
        ("6. Card Network Simulation", demo_card_network),
        ("7. Acquiring Bank Simulation", demo_acquiring_bank),
        ("8. Merchant Checkout Flow", demo_checkout),
        ("9. Merchant Webhook Handler", demo_webhook_handler),
    ]
    
    for title, demo_func in demos:
        print_header(title)
        try:
            demo_func()
        except Exception as e:
            print(f"\n⚠️  Error in demo: {e}")
        input("\n[Press Enter to continue...]\n")
    
    print_header("✅ DEMO COMPLETE")
    print("""
    You've seen the complete payment processing flow!
    
    Next steps:
    1. Read the documentation in /docs for deeper understanding
    2. Explore the source code in /src
    3. Run the tests: pytest tests/ -v
    4. Start the API server: python run_demo.py server
    5. Open the checkout UI: open src/checkout_ui/index.html
    
    For interview prep, focus on:
    - The flow from checkout to settlement
    - Security concepts (tokenization, encryption, 3DS)
    - Idempotency and handling failures
    - Webhook verification and processing
    """)


def demo_tokenization():
    """Run tokenization demo."""
    from gateway.tokenization import demo_tokenization
    demo_tokenization()


def demo_authorization():
    """Run authorization demo."""
    from gateway.authorization import demo_authorization
    demo_authorization()


def demo_fraud_detection():
    """Run fraud detection demo."""
    from gateway.fraud_detection import demo_fraud_detection
    demo_fraud_detection()


def demo_webhooks():
    """Run webhooks demo."""
    from gateway.webhooks import demo_webhooks
    demo_webhooks()


def demo_issuing_bank():
    """Run issuing bank demo."""
    from bank_simulator.issuing_bank import demo_issuing_bank
    demo_issuing_bank()


def demo_card_network():
    """Run card network demo."""
    from bank_simulator.card_network import demo_card_network
    demo_card_network()


def demo_acquiring_bank():
    """Run acquiring bank demo."""
    from bank_simulator.acquiring_bank import demo_acquiring_bank
    demo_acquiring_bank()


def demo_checkout():
    """Run checkout demo."""
    from merchant.checkout import demo_checkout
    demo_checkout()


def demo_webhook_handler():
    """Run webhook handler demo."""
    from merchant.webhook_handler import demo_webhook_handler
    demo_webhook_handler()


def run_server():
    """Run the API server."""
    print_header("🚀 STARTING PAYMENT GATEWAY API SERVER")
    from gateway.server import run_server
    run_server()


def main():
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        commands = {
            "all": run_all_demos,
            "tokenize": demo_tokenization,
            "auth": demo_authorization,
            "fraud": demo_fraud_detection,
            "webhooks": demo_webhooks,
            "issuer": demo_issuing_bank,
            "network": demo_card_network,
            "acquirer": demo_acquiring_bank,
            "checkout": demo_checkout,
            "handler": demo_webhook_handler,
            "server": run_server,
            "bank": lambda: (demo_issuing_bank(), demo_card_network(), demo_acquiring_bank()),
        }
        
        if command in commands:
            commands[command]()
        else:
            print(f"Unknown command: {command}")
            print("\nAvailable commands:")
            for cmd in commands:
                print(f"  {cmd}")
    else:
        run_all_demos()


if __name__ == "__main__":
    main()
