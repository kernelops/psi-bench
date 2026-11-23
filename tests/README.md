# Test files

Small, readable input files with a **known intersection**, to try the protocols from the UI
(New run, "On my data", "Upload my files"). All data is made up.

| Folder | Use with (UI option) | Upload in this order | Should find |
|---|---|---|---|
| `pepsi/` | PEPSI: runs on your files (also works with VOLE-PSI) | `1_client_my_contacts.txt`, then `2_server_registered_users.txt` | **4** (12 contacts vs 400 users) |
| `volepsi/` | VOLE-PSI: runs on your files (also works with PEPSI) | `1_receiver_shop_customers.txt`, then `2_sender_newsletter_subscribers.txt` | **12** (60 vs 80) |
| `bzs-mpsi/` | BZS-MPSI: runs on your files, or the multi-party baseline | `1_client_a.txt`, `2_client_b.txt`, `3_pivot.txt`, `4_leader.txt` | **8** (4 parties) |

Each folder also has `expected_intersection.txt`, the elements that should come out.

- **File order is the party order.** The first file is the client or receiver; for the multi-party tests the last file is
  the leader. Select the files in the order above (the numbers in the names keep them sorted).
- **Leave "Hash elements to 128 bits" ticked.** The elements are plain text.
- **The run page shows how many elements were found**, in the correctness check (`tp`), with `fp` (wrongly found) and `fn`
  (missed) both 0 when it is right. It does not list the elements themselves yet.
- **`bzs-mpsi/` is a good test of what "intersection" means for several parties:** only the 8 IDs present in all four
  files are returned. Other IDs are shared by three files or by two, and must not appear.
