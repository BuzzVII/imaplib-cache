# imaplib-cache


**imaplib-cache** is a persistent IMAP fetch cache to improve the network performance of the python imaplib library.

The goal of this repository is to have a two line plugin to decrease the network overhead of imaplib in new and existing code when the same emails are accessed multiple times. This removes the need for the user to maintain their own database allowing less code and faster deployment.
