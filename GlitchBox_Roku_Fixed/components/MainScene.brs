sub init()
    m.home = m.top.findNode("homeScene")
    m.details = m.top.findNode("detailsScene")
    m.library = m.top.findNode("libraryScene")
    m.player = m.top.findNode("playerScene")
    m.settings = m.top.findNode("settingsScene")
    m.search = m.top.findNode("searchScene")

    if m.home <> invalid then
        ' Support both legacy and new field names
        if m.home.hasField("openSettings") then m.home.observeField("openSettings", "onOpenSettings")
        if m.home.hasField("openSettingsRequested") then m.home.observeField("openSettingsRequested", "onOpenSettings")

        if m.home.hasField("openSearch") then m.home.observeField("openSearch", "onOpenSearch")
        if m.home.hasField("openSearchRequested") then m.home.observeField("openSearchRequested", "onOpenSearch")

        if m.home.hasField("selectedItem") then m.home.observeField("selectedItem", "onHomeSelectedItem")
    end if

    if m.settings <> invalid then m.settings.observeField("backRequested", "onSettingsBack")
    if m.search <> invalid then m.search.observeField("backRequested", "onSearchBack")
    if m.player <> invalid then m.player.observeField("backRequested", "onPlayerBack")
    if m.details <> invalid then m.details.observeField("backRequested", "onDetailsBack")

    ' m.top.setFocus(true)  ' removed to avoid MainScene stealing focus
    showHome()
end sub

sub showHome()
    if m.home <> invalid then m.home.visible = true
    if m.details <> invalid then m.details.visible = false
    if m.library <> invalid then m.library.visible = false
    if m.player <> invalid then m.player.visible = false
    if m.settings <> invalid then m.settings.visible = false
    if m.search <> invalid then m.search.visible = false

    ' Give focus to the Home scene, then to a focusable child (nav list / rows)
    if m.home <> invalid then
        ' Give focus to HomeScene container first so its children can receive focus
        m.home.setFocus(true)
    end if
    focusHomeDefault()
    ' m.top.setFocus(true)  ' removed to avoid MainScene stealing focus
end sub

sub onHomeSelectedItem(event as Object)
    if event = invalid then return

    item = event.getData()
    if item = invalid then return

    ' Hide Home
    if m.home <> invalid then m.home.visible = false

    ' Hide other scenes
    if m.library <> invalid then m.library.visible = false
    if m.player <> invalid then m.player.visible = false
    if m.settings <> invalid then m.settings.visible = false
    if m.search <> invalid then m.search.visible = false

    ' Show Details by default (safe landing). DetailsScene can decide whether to show play actions.
    if m.details <> invalid then
        m.details.visible = true
        m.details.setFocus(true)

        ' If DetailsScene exposes a field for the selected item, set it.
        if m.details.hasField("item") then
            m.details.item = item
        else if m.details.hasField("content") then
            m.details.content = item
        end if

        ' If DetailsScene has a primary button group or list, focus it.
        actions = m.details.findNode("actions")
        if actions <> invalid then actions.setFocus(true)
    end if
end sub

sub onOpenSettings(event as Object)
    ' Only react when HomeScene signals true
    if event <> invalid and event.getData() <> true then return

    if m.home <> invalid then
        if m.home.hasField("openSettings") then m.home.openSettings = false
        if m.home.hasField("openSettingsRequested") then m.home.openSettingsRequested = false
        m.home.visible = false
    end if

    ' Hide any other scenes that might be visible
    if m.details <> invalid then m.details.visible = false
    if m.library <> invalid then m.library.visible = false
    if m.player <> invalid then m.player.visible = false
    if m.search <> invalid then m.search.visible = false

    if m.settings <> invalid then
        m.settings.visible = true
        m.settings.setFocus(true)

        ' Force focus to SettingsScene's ButtonGroup so remote works immediately
        actions = m.settings.findNode("actions")
        if actions <> invalid then actions.setFocus(true)
    end if
end sub
sub onSettingsBack(event as Object)
    if event <> invalid and event.getData() <> true then return

    if m.settings <> invalid then
        m.settings.backRequested = false
        m.settings.visible = false
    end if
    showHome()
end sub

sub onOpenSearch(event as Object)
    ' Only react when HomeScene signals true
    if event <> invalid and event.getData() <> true then return

    if m.home <> invalid then
        if m.home.hasField("openSearch") then m.home.openSearch = false
        if m.home.hasField("openSearchRequested") then m.home.openSearchRequested = false
        m.home.visible = false
    end if

    ' Hide any other scenes that might be visible
    if m.details <> invalid then m.details.visible = false
    if m.library <> invalid then m.library.visible = false
    if m.player <> invalid then m.player.visible = false
    if m.settings <> invalid then m.settings.visible = false

    if m.search <> invalid then
        m.search.visible = true
        m.search.setFocus(true)

        ' Force focus to a known focusable list inside SearchScene if present
        results = m.search.findNode("results")
        if results <> invalid then results.setFocus(true)
    end if
end sub

sub onSearchBack(event as Object)
    if event <> invalid and event.getData() <> true then return

    if m.search <> invalid then
        m.search.backRequested = false
        m.search.visible = false
    end if
    showHome()
end sub

sub onPlayerBack(event as Object)
    if event <> invalid and event.getData() <> true then return

    if m.player <> invalid then
        m.player.backRequested = false
        m.player.visible = false
    end if
    showHome()
end sub

sub onDetailsBack(event as Object)
    if event <> invalid and event.getData() <> true then return

    if m.details <> invalid then
        m.details.backRequested = false
        m.details.visible = false
    end if
    showHome()
end sub

sub focusHomeDefault()
    if m.home = invalid then return

    ' Prefer the left nav if present
    nav = m.home.findNode("navList")
    if nav <> invalid then
        nav.setFocus(true)
        return
    end if

    ' Otherwise try the main rows
    rows = m.home.findNode("rows")
    if rows <> invalid then
        rows.setFocus(true)
        return
    end if

    ' Otherwise try a retry/action button group if present
    actions = m.home.findNode("connectionActions")
    if actions <> invalid then
        actions.setFocus(true)
        return
    end if
end sub
