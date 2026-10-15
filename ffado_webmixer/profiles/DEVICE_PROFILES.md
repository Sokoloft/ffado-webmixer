# FFADO device profiles

Device XML files are generated from the supplied libffado `configuration` file.
Each exact vendor/configuration-model match inherits its family's `common.xml`.
The model ID is the **post-normalization FFADO configuration lookup ID**,
not necessarily the physical ConfigRom ID or `Info/Model` enum.

Only controls actually enumerated by FFADO are used by the mixer. The
existing family control specifications are retained; no unverified ranges,
control methods, or device capabilities were invented. For many families,
`common.xml` contains source-derived discovery paths but no writable numeric
control specifications, so device support remains partial or read-only.
`reference.xml` is source-extracted archival information, not executable code.

The application reads the installed FFADO configuration at runtime. These
model files annotate known device identities and can be extended as bug reports
arrive.
