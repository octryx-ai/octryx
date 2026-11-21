// Custom REST as a Knowledge source (backend kind `custom_rest`): the form state and its defaults, the rules
// (role, dot paths, version or updated, who may choose "workspace"), the request body, the dry run's answer, the
// status with its ACL notice, and every refusal in words. Pure: no React.
//
// The role rule, the dot-path rule and the operation shape are the Work intake's (`restIntakeModel.ts`), because both
// read through the same REST executor and grants.

import { DOT_PATH_HINT } from "../../../../chat/work/intake/restIntakeForm";
import type { Pair, RestOperationInfo } from "../../../../chat/work/intake/restIntakeForm";
