# Full conversion engine

See the [root deployment guide](../README.md#5b-deploy-and-run-the-full-platform) for the complete setup and run sequence.

Included: source hashing/profiling, YAML-driven reshape and mappings, SQL staging, 111 rule definitions, AI triage/mapping-draft helpers, cleansing proposals, six gate records, a metadata-driven destination-procedure emulator, reconciliation, validation samples, generated integrity reports and take-over-take comparisons.

`clients/sample` is an illustrative template with legacy-derived business assumptions. The default input is entirely invented and generated locally. Review every mapping, setup code, exclusion and open question for the recipient's environment. No original customer answer key or approval is included.

The full Direct Lake model reads the lakehouse `rpt_*` tables produced by `nb_publish`. The four-page report definition is bundled. Additional pages mentioned in the design brief are proposals, not deployed report pages.

For an actual GP/CSM destination, replace the emulator through the application's supported business interface and independently test all procedure contracts. Database and CLI gate records do not replace production authorisation.
