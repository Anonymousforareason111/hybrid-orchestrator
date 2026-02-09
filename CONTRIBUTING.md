# Contributing

We welcome contributions to the Hybrid Orchestrator project.

## How to Contribute

1. **Fork the repository**
2. **Create a feature branch** (`git checkout -b feature/your-feature`)
3. **Write tests** for your changes
4. **Run the test suite** (`pytest tests/ -v`)
5. **Submit a pull request**

## Development Setup

```bash
git clone https://github.com/pavelsukhachev/hybrid-orchestrator.git
cd hybrid-orchestrator
pip install -e ".[dev]"
pytest tests/ -v
```

## What We Need Help With

- **New channel adapters** (Slack, SMS via Twilio, Dashboard WebSocket)
- **PostgreSQL storage adapter** (currently SQLite only)
- **Additional trigger types** for different domains
- **Documentation improvements**
- **Bug fixes and test coverage**

## Guidelines

- Write tests for all new functionality
- Follow existing code style
- Keep commits focused and descriptive
- Update documentation for user-facing changes

## Code of Conduct

Be respectful. Be constructive. Focus on the work.

## License

By contributing, you agree that your contributions will be licensed under the Apache 2.0 License.
