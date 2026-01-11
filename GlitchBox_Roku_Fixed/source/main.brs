sub Main()
  screen = CreateObject("roSGScreen")
  port = CreateObject("roMessagePort")
  screen.SetMessagePort(port)

  ' Create the root scene
  scene = screen.CreateScene("MainScene")

  ' SceneGraph global node (for app-wide signals like Exit App)
  globalNode = screen.GetGlobalNode()

  ' Ensure the exitApp field exists on the global node
  if globalNode <> invalid and (not globalNode.hasField("exitApp")) then
    globalNode.addField("exitApp", "bool", false)
  end if

  ' Listen for exit requests
  if globalNode <> invalid then
    globalNode.ObserveField("exitApp", port)
  end if

  screen.Show()

  while true
    msg = wait(0, port)

    if type(msg) = "roSGScreenEvent" then
      if msg.isScreenClosed() then return

    else if type(msg) = "roSGNodeEvent" then
      if msg.getField() = "exitApp" and msg.getData() = true then
        screen.Close()
        return
      end if
    end if
  end while
end sub