Feature: quickmarks

    ## quickmarks

    Scenario: Saving a quickmark (:quickmark-add)
        When I run :quickmark-add http://localhost:(port)/data/numbers/9.txt nine
        Then the quickmark file should contain "nine http://localhost:*/data/numbers/9.txt"

    @flaky
    Scenario: Saving a quickmark (:quickmark-save)
        When I open data/numbers/10.txt
        And I run :quickmark-save
        And I wait for "Entering mode KeyMode.prompt (reason: question asked)" in the log
        And I press the keys "ten"
        And I press the keys "<Enter>"
        Then the quickmark file should contain "ten http://localhost:*/data/numbers/10.txt"

    Scenario: Saving a duplicate quickmark (without override)
        When I run :quickmark-add http://localhost:(port)/data/numbers/11.txt eleven
        And I run :quickmark-add http://localhost:(port)/data/numbers/11_2.txt eleven
        And I wait for "Entering mode KeyMode.yesno (reason: question asked)" in the log
        And I run :prompt-accept no
        Then the quickmark file should contain "eleven http://localhost:*/data/numbers/11.txt"

    Scenario: Saving a duplicate quickmark (with override)
        When I run :quickmark-add http://localhost:(port)/data/numbers/12.txt twelve
        And I run :quickmark-add http://localhost:(port)/data/numbers/12_2.txt twelve
        And I wait for "Entering mode KeyMode.yesno (reason: question asked)" in the log
        And I run :prompt-accept yes
        Then the quickmark file should contain "twelve http://localhost:*/data/numbers/12_2.txt"

    Scenario: Adding a quickmark with an empty name
        When I run :quickmark-add about:blank ""
        Then the error "Can't set mark with empty name!" should be shown

    Scenario: Adding a quickmark with an empty URL
        When I run :quickmark-add "" foo
        Then the error "Can't set mark with empty URL!" should be shown

    Scenario: Loading a quickmark
        Given I have a fresh instance
        When I run :quickmark-add http://localhost:(port)/data/numbers/13.txt thirteen
        And I run :quickmark-load thirteen
        Then data/numbers/13.txt should be loaded
        And the following tabs should be open:
            """
            - data/numbers/13.txt (active)
            """

    Scenario: Loading a quickmark in a new tab
        Given I open about:blank
        When I run :tab-only
        And I run :quickmark-add http://localhost:(port)/data/numbers/14.txt fourteen
        And I run :quickmark-load -t fourteen
        Then data/numbers/14.txt should be loaded
        And the following tabs should be open:
            """
            - about:blank
            - data/numbers/14.txt (active)
            """

    Scenario: Loading a quickmark in a background tab
        Given I open about:blank
        When I run :tab-only
        And I run :quickmark-add http://localhost:(port)/data/numbers/15.txt fifteen
        And I run :quickmark-load -b fifteen
        Then data/numbers/15.txt should be loaded
        And the following tabs should be open:
            """
            - about:blank (active)
            - data/numbers/15.txt
            """

    Scenario: Loading a quickmark in a new window
        Given I open about:blank
        When I run :tab-only
        And I run :quickmark-add http://localhost:(port)/data/numbers/16.txt sixteen
        And I run :quickmark-load -w sixteen
        And I wait until data/numbers/16.txt is loaded
        Then the session should look like:
            """
            windows:
            - tabs:
              - active: true
                history:
                - active: true
                  url: about:blank
            - tabs:
              - active: true
                history:
                - active: true
                  url: http://localhost:*/data/numbers/16.txt
            """

    Scenario: Loading a quickmark which does not exist
        When I run :quickmark-load -b doesnotexist
        Then the error "Quickmark 'doesnotexist' does not exist!" should be shown

    Scenario: Loading a quickmark with -t and -b
        When I run :quickmark-add http://localhost:(port)/data/numbers/17.txt seventeen
        When I run :quickmark-load -t -b seventeen
        Then the error "Only one of -t/-b/-w/-p can be given!" should be shown

    Scenario: Deleting a quickmark which does not exist
        When I run :quickmark-del doesnotexist
        Then the error "Quickmark 'doesnotexist' not found!" should be shown

    Scenario: Deleting a quickmark
        When I run :quickmark-add http://localhost:(port)/data/numbers/18.txt eighteen
        And I run :quickmark-del eighteen
        Then the quickmark file should not contain "eighteen http://localhost:*/data/numbers/18.txt "

    Scenario: Deleting all quickmarks
        When I run :quickmark-add http://localhost:(port)/data/numbers/1.txt one
        When I run :quickmark-add http://localhost:(port)/data/numbers/2.txt two
        And I run :quickmark-del --all
        Then the message "Quickmarks cleared." should be shown
        And the quickmark file should not contain "one http://localhost:*/data/numbers/1.txt"
        And the quickmark file should not contain "two http://localhost:*/data/numbers/2.txt"

    Scenario: Deleting all quickmarks with name
        When I run :quickmark-add http://localhost:(port)/data/numbers/1.txt one
        And I run :quickmark-del --all invalid
        Then the error "Cannot specify name and --all" should be shown
        And the quickmark file should contain "one http://localhost:*/data/numbers/1.txt"

    Scenario: Deleting the current page's quickmark if it has none
        When I open data/hello.txt
        And I run :quickmark-del
        Then the error "Quickmark for 'http://localhost:(port)/data/hello.txt' not found!" should be shown

    Scenario: Deleting the current page's quickmark
        When I open data/numbers/19.txt
        And I run :quickmark-add http://localhost:(port)/data/numbers/19.txt nineteen
        And I run :quickmark-del
        Then the quickmark file should not contain "nineteen http://localhost:*/data/numbers/19.txt"

    Scenario: Listing quickmarks
        When I run :quickmark-add http://localhost:(port)/data/numbers/20.txt twenty
        And I run :quickmark-add http://localhost:(port)/data/numbers/21.txt twentyone
        And I open qute://quickmarks
        Then the page should contain the plaintext "twenty"
        And the page should contain the plaintext "twentyone"

    Scenario: Following a quickmark
        When I run :quickmark-add http://localhost:(port)/data/numbers/1.txt one
        And I open qute://quickmarks in a new tab
        And I hint with args "links current" and follow a
        Then data/numbers/1.txt should be loaded

    Scenario: Following a quickmark and going back/forward
        When I run :quickmark-add http://localhost:(port)/data/numbers/1.txt one
        And I open qute://quickmarks in a new tab
        And I hint with args "links current" and follow a
        And I wait until data/numbers/1.txt is loaded
        And I run :back
        And I wait until qute://quickmarks is loaded
        And I run :forward
        Then data/numbers/1.txt should be loaded

    Scenario:
        When I run :quickmarks-reload
        Then the message "Quickmarks reloaded." should be shown
