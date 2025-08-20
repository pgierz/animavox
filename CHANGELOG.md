# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Distributed CRDT Synchronization**: New `DistributedTelepathicObject` class for P2P collaboration
  - Delta-only synchronization for efficient network usage
  - Automatic peer synchronization on connection
  - State request/response cycle for initial sync
  - Robust error handling for network failures and invalid data
  - Both synchronous and asynchronous API support
- CRDT message types and serialization with JSON and base64 encoding
- Comprehensive test suite with 34 passing tests (94.4% success rate)
- MIT License added to the project

### Changed
- Enhanced `TelepathicObject` to support distributed scenarios
- Improved error handling to gracefully handle CRDT library panics

### Performance
- **Major Performance Improvement**: Delta synchronization reduces network bandwidth by sending only changes instead of full document state
- Demonstration shows individual operations using 36-85 bytes instead of full state

## [0.1.0] - Development Version

### Added
- Initial implementation of `TelepathicObject` with CRDT support
- CLI interface for managing data structures
- Transaction logging and versioning
- TUI with paging functionality
- Object serialization and deserialization
- Basic networking components

### Features
- CRDT-based conflict-free data structures using `pycrdt`
- Rich CLI with `rich-click` integration  
- Transaction history and logging
- Data path utilities with `dpath`

### Dependencies
- `pycrdt>=0.12.26,<0.13` - Core CRDT functionality
- `rich-click>=1.8.9,<2` - CLI interface
- `dpath>=2.2.0,<3` - Data path utilities
- `asyncio>=3.4.3,<4` - Asynchronous operations

---

## Version History Notes

- **v0.3.0**: Better TUI with improved paging (work in progress)
- **v0.2.0**: Sorting by operation index counter (work in progress) 
- **v0.1.0**: Basic functionality working (work in progress)

## Future Roadmap

- [ ] Performance optimizations for large documents
- [ ] Vector clocks for operation ordering
- [ ] Multi-peer mesh network support
- [ ] WebSocket transport layer
- [ ] Real-time collaborative editing demo
- [ ] Documentation with Sphinx/JupyterBook
- [ ] Continuous Integration setup
- [ ] PyPI package distribution