# Changelog

## [0.0.11](https://github.com/bakerkj/ha-aruba-ap/compare/v0.0.10...v0.0.11) (2026-05-11)


### Miscellaneous Chores

* migrate prettier hook to maintained rbubley mirror ([#31](https://github.com/bakerkj/ha-aruba-ap/issues/31)) ([0dc1020](https://github.com/bakerkj/ha-aruba-ap/commit/0dc10209dd0d7211bc8a74249ceef5a830b9d010))
* rename default branch from master to main ([#29](https://github.com/bakerkj/ha-aruba-ap/issues/29)) ([b4c83ab](https://github.com/bakerkj/ha-aruba-ap/commit/b4c83ab8ae98b93265fdb83f3cfdd680b122583d))


### Continuous Integration

* distinct setup-uv cache keys for tests and pre-commit jobs ([#32](https://github.com/bakerkj/ha-aruba-ap/issues/32)) ([86ed493](https://github.com/bakerkj/ha-aruba-ap/commit/86ed4938efd93269788a020f9a4480caac7b2c7e))
* pin ubuntu-latest runners to ubuntu-24.04 for renovate tracking ([#33](https://github.com/bakerkj/ha-aruba-ap/issues/33)) ([9348294](https://github.com/bakerkj/ha-aruba-ap/commit/9348294a645b8c70d110c7edca21a3d69ef91acf))
* run mypy against real runtime deps, drop --ignore-missing-imports ([#34](https://github.com/bakerkj/ha-aruba-ap/issues/34)) ([00fe91d](https://github.com/bakerkj/ha-aruba-ap/commit/00fe91df6696093a8e7887d41d7de403b19508b6))
* skip mypy in the pre-commit CI workflow ([#35](https://github.com/bakerkj/ha-aruba-ap/issues/35)) ([21b3120](https://github.com/bakerkj/ha-aruba-ap/commit/21b3120b86882dd0e612b0138c7421e5b4041ec1))

## [0.0.10](https://github.com/bakerkj/ha-aruba-ap/compare/v0.0.9...v0.0.10) (2026-05-10)


### Continuous Integration

* grant release workflow contents:write for asset upload ([#27](https://github.com/bakerkj/ha-aruba-ap/issues/27)) ([ff0f5f7](https://github.com/bakerkj/ha-aruba-ap/commit/ff0f5f723baeb04c361e990b6cdd0135f332043b))

## [0.0.9](https://github.com/bakerkj/ha-aruba-ap/compare/v0.0.8...v0.0.9) (2026-05-10)


### Features

* automate releases with release-please and commitlint ([#21](https://github.com/bakerkj/ha-aruba-ap/issues/21)) ([beaa26f](https://github.com/bakerkj/ha-aruba-ap/commit/beaa26f770fae7a2320150ba7d2dfc9c7aebef33))


### Miscellaneous Chores

* **deps:** update astral-sh/setup-uv action to v8 ([6609292](https://github.com/bakerkj/ha-aruba-ap/commit/6609292862fa2d75ffde4714dc6477738cff1c41))
* **deps:** update astral-sh/setup-uv action to v8 ([8cb0c61](https://github.com/bakerkj/ha-aruba-ap/commit/8cb0c617767d514ac384d92968d97c161cb83d7a))
* **deps:** update github-actions ([#24](https://github.com/bakerkj/ha-aruba-ap/issues/24)) ([55b77b6](https://github.com/bakerkj/ha-aruba-ap/commit/55b77b6ac89b12a17af8aeb485e732aa56a2c20f))
* **deps:** update pre-commit hook alessandrojcm/commitlint-pre-commit-hook to v9.25.0 ([#23](https://github.com/bakerkj/ha-aruba-ap/issues/23)) ([0340941](https://github.com/bakerkj/ha-aruba-ap/commit/03409416515c99db855872a00f7b99763174ca04))
* **deps:** update pre-commit hook pre-commit/mirrors-mypy to v2 ([#20](https://github.com/bakerkj/ha-aruba-ap/issues/20)) ([a15ac39](https://github.com/bakerkj/ha-aruba-ap/commit/a15ac396681f8f098d25b7bf67da4486c073a18d))
* **deps:** update pre-commit hook python-jsonschema/check-jsonschema to v0.37.2 ([#18](https://github.com/bakerkj/ha-aruba-ap/issues/18)) ([533a581](https://github.com/bakerkj/ha-aruba-ap/commit/533a581f3cc926af106cca7653b095c83aaca610))
* **deps:** update pre-commit hooks ([4ec013b](https://github.com/bakerkj/ha-aruba-ap/commit/4ec013b0406f00855ec9775677380e19dca3f585))
* **deps:** update pre-commit hooks ([b641df5](https://github.com/bakerkj/ha-aruba-ap/commit/b641df525f8f543979d4f3fe6a6fd7ca02e469ff))


### Continuous Integration

* align prettier with release-please's manifest.json output ([#26](https://github.com/bakerkj/ha-aruba-ap/issues/26)) ([04e6711](https://github.com/bakerkj/ha-aruba-ap/commit/04e6711f00cca545d1a16d073bc82f0da7ac6619))
* make all conventional commit types visible in release-please changelog-sections ([#25](https://github.com/bakerkj/ha-aruba-ap/issues/25)) ([e82448c](https://github.com/bakerkj/ha-aruba-ap/commit/e82448c60c42b60f73eecd96034bbb842c1dfd27))
